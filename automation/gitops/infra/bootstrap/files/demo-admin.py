"""Initialize the synthetic Mattermost administrator without logging credentials."""
import base64
import json
import secrets
import ssl
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def main():
    root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    kube = build_opener(NoRedirect, HTTPSHandler(context=ssl.create_default_context(cafile=str(root / 'ca.crt'))))
    url = 'https://kubernetes.default.svc/api/v1/namespaces/openshell-agents/secrets/saw-demo-admin'
    headers = {'Authorization': 'Bearer ' + (root / 'token').read_text().strip(), 'Content-Type': 'application/merge-patch+json'}
    with kube.open(Request(url, headers=headers), timeout=30) as response:
        secret = json.load(response)
    encoded = secret.get('data', {}).get('state')
    fresh = not encoded
    state = json.loads(base64.b64decode(encoded)) if encoded else {'username': 'saw-lab-admin', 'password': secrets.token_urlsafe(32)}
    if fresh:
        payload = {'metadata': {'resourceVersion': secret['metadata']['resourceVersion']},
                   'data': {'state': base64.b64encode(json.dumps(state).encode()).decode()}}
        with kube.open(Request(url, data=json.dumps(payload).encode(), headers=headers, method='PATCH'), timeout=30): pass
    backend = 'http://mattermost.openshell-agents.svc.cluster.local:8065/api/v4'
    http = build_opener(NoRedirect)
    def login():
        request = Request(backend + '/users/login', data=json.dumps({'login_id': state['username'], 'password': state['password']}).encode(), headers={'Content-Type': 'application/json'})
        with http.open(request, timeout=30) as response:
            return json.load(response)
    try:
        user = login()
    except HTTPError as error:
        if error.code not in (401, 404): raise
        # A saved password may precede backend readiness on a retried first boot.
        request = Request(backend + '/users', data=json.dumps({'username': state['username'],
            'password': state['password'], 'email': 'saw-lab-admin@example.test'}).encode(), headers={'Content-Type': 'application/json'})
        with http.open(request, timeout=30): pass
        user = login()
    if 'system_admin' not in user.get('roles', '').split():
        raise ValueError('Configured account is not a Mattermost administrator')
    print('Synthetic Mattermost administrator verified')


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, KeyError):
        raise SystemExit('Demo administrator setup failed; verify readiness or adopt existing private administrator credentials') from None
