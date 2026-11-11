"""Create or reconcile a workshop-owned OpenShell Keycloak account."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

base = 'http://openshell-keycloak-service.saw-keycloak.svc:8080'
name = os.environ['SAW_USER']
password = Path('/input/password').read_text().strip()
admin = Path('/admin/username').read_text().strip()
admin_password = Path('/admin/password').read_text().strip()
form = urlencode({'grant_type': 'password', 'client_id': 'admin-cli',
                  'username': admin, 'password': admin_password}).encode()
with urlopen(Request(base + '/realms/master/protocol/openid-connect/token', data=form), timeout=30) as response:
    token = json.load(response)['access_token']


def api(path, method='GET', body=None):
    payload = None if body is None else json.dumps(body).encode()
    request = Request(base + '/admin/realms/openshell' + path, data=payload, method=method,
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        result = response.read()
        return json.loads(result) if result else None


query = '/users?' + urlencode({'username': name, 'exact': 'true'})
users = api(query)
if len(users) > 1:
    raise SystemExit('Multiple matching OpenShell users')
created = not users
if created:
    api('/users', 'POST', {'username': name, 'firstName': name, 'lastName': 'User',
                          'email': name + '@openshell.local', 'emailVerified': True,
                          'enabled': True,
                          'credentials': [{'type': 'password', 'value': password, 'temporary': False}]})
    users = api(query)
if len(users) != 1:
    raise SystemExit('OpenShell user lookup failed')
user_id = users[0]['id']
if not created:
    form = urlencode({'grant_type': 'password', 'client_id': 'openshell-cli',
                      'username': name, 'password': password}).encode()
    try:
        with urlopen(Request(base + '/realms/openshell/protocol/openid-connect/token', data=form), timeout=30):
            pass
    except HTTPError:
        raise SystemExit('Existing account password could not be verified; refusing to reset it') from None
role = api('/roles/openshell-user')
api('/users/' + user_id + '/role-mappings/realm', 'POST', [role])
print('Workshop OpenShell account ready')
