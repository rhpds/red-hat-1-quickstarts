"""Bootstrap the dedicated SAW workshop Vault without logging credentials."""
import base64
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request


class API:
    def __init__(self, url, ca, token='', header='X-Vault-Token'):
        self.url, self.token, self.header = url, token, header
        self.context = ssl.create_default_context(cafile=ca)

    def call(self, path, data=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers[self.header] = self.token
        request = urllib.request.Request(self.url + path,
                                         data=None if data is None else json.dumps(data).encode(),
                                         headers=headers, method=method)
        with urllib.request.urlopen(request, context=self.context, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else {}


def encode(value):
    return base64.b64encode(value.encode()).decode()


def decode(value):
    return base64.b64decode(value).decode()


def bootstrap(vault, kube, namespace, state_name, writer_name, writer_key,
              run_id, eso_namespace, eso_account, ingress_ca):
    prefix = f'/api/v1/namespaces/{namespace}/secrets/'
    state = kube.call(prefix + state_name)
    status = vault.call('/sys/seal-status')
    saved = state.get('data', {}).get('init.json')
    if not saved:
        if status['initialized']:
            raise RuntimeError('Vault is initialized but bootstrap credentials are missing; restore the bootstrap Secret or use externally managed Vault mode')
        # Kubernetes resourceVersion makes competing initializers fail before init.
        annotations = state['metadata'].setdefault('annotations', {})
        owner = annotations.get('saw.redhat.com/initializer')
        if owner and owner != run_id:
            raise RuntimeError('Another bootstrap owns initialization; inspect its Job before retrying')
        annotations['saw.redhat.com/initializer'] = run_id
        state = kube.call(prefix + state_name, state, 'PUT')
        credentials = vault.call('/sys/init', {'secret_shares': 1, 'secret_threshold': 1}, 'PUT')
        state.setdefault('data', {})['init.json'] = encode(json.dumps(credentials))
        # Retry storage, NEVER initialization. Fail closed if the process is lost
        # between Vault initialization and persisting its response.
        for attempt in range(6):
            try:
                state = kube.call(prefix + state_name, state, 'PUT')
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise RuntimeError('Unable to persist Vault initialization; do not delete the PVC') from None
                time.sleep(2)
                current = kube.call(prefix + state_name)
                state['metadata']['resourceVersion'] = current['metadata']['resourceVersion']
    else:
        if not status['initialized']:
            raise RuntimeError('Saved Vault credentials exist but Vault is uninitialized; restore the matching PVC')
        credentials = json.loads(decode(saved))
    if not credentials.get('root_token') or not credentials.get('keys_base64'):
        raise RuntimeError('Incomplete Vault bootstrap credentials; refusing to replace them')
    if status['sealed']:
        for key in credentials['keys_base64']:
            status = vault.call('/sys/unseal', {'key': key}, 'PUT')
            if not status['sealed']:
                break
        if status['sealed']:
            raise RuntimeError('Stored keys did not unseal Vault')
    vault.token = credentials['root_token']
    mounts = vault.call('/sys/mounts')['data']
    if 'secret/' not in mounts:
        vault.call('/sys/mounts/secret', {'type': 'kv', 'options': {'version': '2'}})
    elif mounts['secret/']['type'] != 'kv' or mounts['secret/'].get('options', {}).get('version') != '2':
        raise RuntimeError('Existing secret/ mount is not KV v2; refusing to replace it')
    auth = vault.call('/sys/auth')['data']
    if 'hub/' not in auth:
        vault.call('/sys/auth/hub', {'type': 'kubernetes'})
    elif auth['hub/']['type'] != 'kubernetes':
        raise RuntimeError('Existing hub/ auth is not Kubernetes; refusing to replace it')
    # Vault uses its own rotating in-pod SA token and CA for TokenReview.
    vault.call('/auth/hub/config', {'kubernetes_host': 'https://kubernetes.default.svc:443'})
    vault.call('/sys/policies/acl/saw-external-secrets', {'policy':
        'path "secret/data/hub/*" { capabilities = ["read"] }\n'
        'path "secret/metadata/hub/*" { capabilities = ["read", "list"] }'})
    vault.call('/auth/hub/role/hub-role', {
        'bound_service_account_names': [eso_account],
        'bound_service_account_namespaces': [eso_namespace],
        'token_policies': ['saw-external-secrets'], 'token_ttl': '1h'})
    vault.call('/sys/policies/acl/saw-writer', {'policy':
        'path "secret/data/hub/*" { capabilities = ["create", "read", "update"] }'})
    writer = kube.call(prefix + writer_name)
    existing = writer.get('data', {}).get(writer_key)
    if existing:
        root = vault.token
        vault.token = decode(existing)
        try:
            # Preserve a supplied/existing valid writer token. Expired tokens are replaced.
            vault.call('/auth/token/lookup-self')
        except urllib.error.HTTPError as error:
            error.close()
            if error.code != 403:
                raise
            existing = None
        finally:
            vault.token = root
    if not existing:
        token = vault.call('/auth/token/create-orphan', {
            'policies': ['saw-writer'], 'ttl': '768h', 'renewable': True,
            'display_name': 'saw-writer'})['auth']['client_token']
        writer.setdefault('data', {})[writer_key] = encode(token)
        kube.call(prefix + writer_name, writer, 'PUT')
    # Refresh only the public ingress CA, preserving concurrent writes with CAS.
    path = '/secret/data/hub/cluster-ingress-ca'
    try:
        ca = vault.call(path)['data']
    except urllib.error.HTTPError as error:
        error.close()
        if error.code != 404:
            raise
        ca = {'data': {}, 'metadata': {'version': 0}}
    if ca['data'].get('ca-bundle.crt') != ingress_ca:
        vault.call(path, {'options': {'cas': ca['metadata']['version']},
                         'data': {**ca['data'], 'ca-bundle.crt': ingress_ca}})
    print('Vault initialized, unsealed and configured; bootstrap credentials retained in its Kubernetes Secret')


def main():
    sa = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    vault = API(os.environ['VAULT_URL'] + '/v1', '/ca/service-ca.crt')
    kube = API('https://kubernetes.default.svc', str(sa / 'ca.crt'),
               'Bearer ' + (sa / 'token').read_text().strip(), 'Authorization')
    bootstrap(vault, kube, os.environ['VAULT_NAMESPACE'], os.environ['STATE_SECRET'],
              os.environ['WRITER_SECRET'], os.environ['WRITER_KEY'], os.environ['RUN_ID'],
              os.environ['ESO_NAMESPACE'], os.environ['ESO_ACCOUNT'],
              Path('/ingress-ca/ca-bundle.crt').read_text())


if __name__ == '__main__':
    try:
        main()
    except (urllib.error.URLError, TimeoutError):
        # HTTP response bodies can contain sensitive data. Never log them.
        raise SystemExit('Vault bootstrap API request failed; check service readiness, TLS, permissions and bootstrap Secret') from None
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
