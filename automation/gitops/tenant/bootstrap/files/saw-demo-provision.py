"""Populate a tenant's synthetic sources and publish only its provider credentials."""
import argparse
import base64
import importlib.util
import json
import os
import ssl
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

spec = importlib.util.spec_from_file_location('seed_demo', Path(__file__).with_name('seed-demo.py'))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def kube(namespace, name, body=None):
    root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    request = Request(f'https://kubernetes.default.svc/api/v1/namespaces/{namespace}/secrets/{name}',
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={'Authorization': 'Bearer ' + (root / 'token').read_text().strip(),
                               'Content-Type': 'application/merge-patch+json'},
                      method='PATCH' if body is not None else 'GET')
    opener = build_opener(seed.NoRedirect, HTTPSHandler(context=ssl.create_default_context(cafile=str(root / 'ca.crt'))))
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def configure(user, password, issuer, admin_state, state_path, vault, action='seed'):
    if action not in ('seed', 'verify', 'challenge', 'reset'):
        raise ValueError('Unsupported demo action')
    # Verify the provisioned password before creating or changing any source data.
    identity = seed.Client(issuer)
    body, _ = identity.request('POST', '/protocol/openid-connect/token',
        urlencode({'grant_type': 'password', 'client_id': 'openshell-cli',
                   'username': user, 'password': password}), 'application/x-www-form-urlencoded')
    if not json.loads(body).get('access_token'):
        raise RuntimeError('Provisioned Keycloak login failed')
    urls = {'mailpit_url': 'http://mailpit.openshell-agents.svc.cluster.local:8025',
            'mattermost_url': 'http://mattermost.openshell-agents.svc.cluster.local:8065',
            'radicale_url': 'http://radicale.openshell-agents.svc.cluster.local:5232'}
    args = argparse.Namespace(action=action, demo_id=user, username=user,
                              state=state_path, date=None, **urls)
    reuse = False
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get('username') != user or state.get('demo_id') != user:
            raise ValueError('Saved demo state belongs to a different tenant')
        if action != 'seed':
            seed.run(args)
            return state
        try:
            current = seed.Client(urls['mattermost_url'], state['mattermost_token']).json('GET', '/api/v4/users/me')
            reuse = current.get('username') == user
        except RuntimeError:
            pass
    if action != 'seed':
        raise ValueError('Seed this tenant before running a demo action')
    os.environ['SAW_DEMO_PASSWORD'] = password
    if reuse:
        os.environ.pop('MATTERMOST_ADMIN_TOKEN', None)
    else:
        admin = seed.Client(urls['mattermost_url'])
        _, headers = admin.request('POST', '/api/v4/users/login',
            {'login_id': admin_state['username'], 'password': admin_state['password']})
        token = headers.get('Token')
        if not token:
            raise RuntimeError('Demo administrator session unavailable')
        os.environ['MATTERMOST_ADMIN_TOKEN'] = token
    seed.run(args)
    args.action = 'verify'
    seed.run(args)
    state = json.loads(state_path.read_text())
    authorization = 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()
    for source, credential in [('mailpit', authorization), ('calendar', authorization),
                               ('mattermost', state['mattermost_token'])]:
        vault(source, {'provider': source, 'api_key': credential})
    return state


def main():
    user = os.environ['SAW_USER']
    password = Path('/input/password').read_text().rstrip('\r\n')
    name = 'saw-' + user + '-demo-state'
    saved = kube('vault', name)
    path = Path('/work/state.json')
    if saved.get('data', {}).get('state'):
        seed.save_state(path, json.loads(base64.b64decode(saved['data']['state'])))
    admin_secret = kube('openshell-agents', 'saw-demo-admin')
    admin = json.loads(base64.b64decode(admin_secret['data']['state']))
    token = Path('/vault-token/token').read_text().strip()
    opener = build_opener(seed.NoRedirect, HTTPSHandler(context=ssl.create_default_context(cafile='/ca/service-ca.crt')))

    def vault(source, data):
        url = 'https://vault.vault.svc:8200/v1/secret/data/' + os.environ['VAULT_PATH'] + '/' + source
        request = Request(url, data=json.dumps({'data': data}).encode(), method='POST',
                          headers={'X-Vault-Token': token, 'Content-Type': 'application/json'})
        with opener.open(request, timeout=30):
            pass
    try:
        configure(user, password, os.environ['OIDC_ISSUER'], admin, path, vault,
                  action=os.environ.get('SAW_DEMO_ACTION', 'seed'))
    finally:
        # Retain a successful login even if a later service/Vault write failed.
        if path.exists():
            kube('vault', name, {'metadata': {'resourceVersion': saved['metadata']['resourceVersion']},
                                 'data': {'state': base64.b64encode(path.read_bytes()).decode()}})
    print('Tenant demo action completed successfully')


if __name__ == '__main__':
    try:
        main()
    except HTTPError as error:
        raise SystemExit(f'Tenant demo preparation failed: HTTP {error.code} at {urlsplit(error.url).hostname}') from None
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        raise SystemExit(f'Tenant demo preparation failed ({type(error).__name__}); verify identity, readiness and private operator state') from None
