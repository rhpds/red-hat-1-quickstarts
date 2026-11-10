"""Regression coverage for the Admin API audience check in current Keycloak."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'tenant/saw/charts/openshell-keycloak/files'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), FILES / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KeycloakBootstrapTests(unittest.TestCase):
    def test_both_controllers_request_admin_scope_when_available(self):
        for name in ('owner-resolver', 'redirect-registrar'):
            for modern in (True, False):
                with self.subTest(controller=name, modern=modern), tempfile.TemporaryDirectory() as tmp:
                    module = load(name)
                    admin = Path(tmp)
                    (admin / 'username').write_text('test-admin')
                    (admin / 'password').write_text('test-password')
                    calls = []
                    client = {'id': 'controller-id', 'protocol': 'openid-connect', 'publicClient': False,
                              'clientAuthenticatorType': 'client-secret', 'serviceAccountsEnabled': True,
                              'standardFlowEnabled': False, 'directAccessGrantsEnabled': False,
                              'implicitFlowEnabled': False}

                    def api(method, path, body=None, **kwargs):
                        calls.append((method, path, body))
                        if path == '/client-scopes':
                            return [{'id': 'other', 'name': 'profile'}] + ([{'id': 'admin-scope', 'name': 'kc-admin-api'}] if modern else [])
                        if path.endswith('/service-account-user'): return {'id': 'service-user'}
                        if path.endswith('/client-secret'): return {'value': 'test-client-secret'}
                        if path.endswith('/roles/view-users'): return {'id': 'view', 'name': 'view-users'}
                        if path.endswith('/roles/manage-clients'): return {'id': 'manage', 'name': 'manage-clients'}
                        if '/role-mappings/' in path and method == 'GET': return []
                        return {}

                    env = {'KC_URL': 'http://keycloak.invalid', 'REALM': 'openshell', 'CLIENT_ID': 'test-controller',
                           'ADMIN_DIR': tmp, 'OUT': str(admin / 'client-secret')}
                    with mock.patch.dict(os.environ, env):
                        if name == 'owner-resolver':
                            def kc_call(url, realm, token, path, method='GET', body=None, ctx=None):
                                return api(method, path, body)
                            with mock.patch.object(module, 'keycloak_token', return_value='test-token'), \
                                 mock.patch.object(module, 'exact_client', side_effect=lambda url, realm, token, name, ctx: {'id': 'management'} if name == 'realm-management' else client), \
                                 mock.patch.object(module, 'kc_call', side_effect=kc_call):
                                module.bootstrap()
                        else:
                            kc = mock.Mock(side_effect=api)
                            kc.client.side_effect = lambda name: {'id': 'management'} if name == 'realm-management' else client
                            with mock.patch.object(module, 'Keycloak', return_value=kc):
                                module.bootstrap()
                    scope_calls = [(method, path) for method, path, body in calls if '/default-client-scopes/' in path]
                    self.assertEqual(scope_calls, [('PUT', '/clients/controller-id/default-client-scopes/admin-scope')] if modern else [])
                    self.assertEqual((admin / 'client-secret').read_text(), 'test-client-secret')
                    role_calls = [body for method, path, body in calls if method == 'POST' and '/role-mappings/' in path]
                    self.assertEqual(role_calls, [[{'id': 'view', 'name': 'view-users'}]] if name == 'owner-resolver' else [[{'id': 'manage', 'name': 'manage-clients'}]])


if __name__ == '__main__':
    unittest.main()
