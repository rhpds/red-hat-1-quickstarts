import copy
import importlib.util
import json
from pathlib import Path
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap_vault', ROOT / 'infra/ansible/roles/saw_prepare/files/bootstrap_vault.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def error(code):
    return urllib.error.HTTPError('https://example.invalid', code, 'test', {}, None)


class Kube:
    def __init__(self):
        self.secrets = {name: {'metadata': {'name': name, 'resourceVersion': '1'}}
                        for name in ('state', 'writer')}
        self.calls = []

    def call(self, path, data=None, method=None):
        name = path.rsplit('/', 1)[1]
        self.calls.append((name, method))
        if method == 'PUT':
            if data['metadata']['resourceVersion'] != self.secrets[name]['metadata']['resourceVersion']:
                raise error(409)
            value = copy.deepcopy(data)
            value['metadata']['resourceVersion'] = str(int(value['metadata']['resourceVersion']) + 1)
            self.secrets[name] = value
        return copy.deepcopy(self.secrets[name])


class Vault:
    def __init__(self):
        self.initialized = False
        self.sealed = True
        self.token = ''
        self.calls = []
        self.mounts = {}
        self.auth = {}
        self.ca = None
        self.kube = None
        self.expired_writer = False

    def call(self, path, data=None, method=None):
        self.calls.append((path, copy.deepcopy(data)))
        if path == '/sys/seal-status':
            return {'initialized': self.initialized, 'sealed': self.sealed}
        if path == '/sys/init':
            if self.initialized:
                raise AssertionError('must not reinitialize')
            self.initialized = True
            return {'root_token': 'root-test', 'keys_base64': ['unseal-test']}
        if path == '/sys/unseal':
            # Recovery keys must be persisted BEFORE any unseal/configure call.
            assert 'init.json' in self.kube.secrets['state']['data']
            assert data['key'] == 'unseal-test'
            self.sealed = False
            return {'sealed': False}
        if path == '/sys/mounts': return {'data': self.mounts}
        if path == '/sys/mounts/secret': self.mounts['secret/'] = data
        if path == '/sys/auth': return {'data': self.auth}
        if path == '/sys/auth/hub': self.auth['hub/'] = data
        if path == '/auth/token/create-orphan':
            assert data['policies'] == ['saw-writer']
            return {'auth': {'client_token': 'writer-test'}}
        if path == '/auth/token/lookup-self' and self.expired_writer:
            raise error(403)
        if path == '/secret/data/hub/cluster-ingress-ca':
            if data is None:
                if self.ca is None: raise error(404)
                return {'data': self.ca}
            self.ca = {'data': data['data'], 'metadata': {'version': data['options']['cas'] + 1}}
        return {}


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.kube = Kube()
        self.vault = Vault()
        self.vault.kube = self.kube

    def run_bootstrap(self, run='run-one', ca='ingress-test-ca'):
        bootstrap.bootstrap(self.vault, self.kube, 'vault', 'state', 'writer', 'token',
                            run, 'external-secrets', 'ocp-external-secrets', ca)

    def test_fresh_bootstrap_then_repeat_preserves_credentials(self):
        self.run_bootstrap()
        credentials = self.kube.secrets['state']['data'].copy()
        writer = self.kube.secrets['writer']['data'].copy()
        self.assertEqual(bootstrap.decode(writer['token']), 'writer-test')
        role = next(data for path, data in self.vault.calls if path == '/auth/hub/role/hub-role')
        self.assertEqual(role['bound_service_account_names'], ['ocp-external-secrets'])
        self.assertEqual(role['bound_service_account_namespaces'], ['external-secrets'])
        self.vault.calls.clear()
        self.run_bootstrap(run='run-two')
        self.assertEqual(self.kube.secrets['state']['data'], credentials)
        self.assertEqual(self.kube.secrets['writer']['data'], writer)
        paths = [path for path, _ in self.vault.calls]
        for path in ('/sys/init', '/sys/unseal', '/sys/mounts/secret', '/sys/auth/hub', '/auth/token/create-orphan'):
            self.assertNotIn(path, paths)

    def test_sealed_existing_vault_is_unsealed_without_reinitializing(self):
        self.run_bootstrap()
        self.vault.sealed = True
        self.vault.calls.clear()
        self.run_bootstrap(run='run-two')
        self.assertFalse(self.vault.sealed)
        self.assertNotIn('/sys/init', [path for path, _ in self.vault.calls])

    def test_initialized_vault_with_missing_credentials_fails_closed(self):
        self.vault.initialized = True
        with self.assertRaisesRegex(RuntimeError, 'credentials are missing'):
            self.run_bootstrap()
        self.assertEqual(len(self.vault.calls), 1)

    def test_saved_credentials_with_missing_storage_fail_closed(self):
        self.run_bootstrap()
        self.vault.initialized = False
        with self.assertRaisesRegex(RuntimeError, 'matching PVC'):
            self.run_bootstrap()

    def test_competing_initializer_never_calls_init(self):
        self.kube.secrets['state']['metadata']['annotations'] = {'saw.redhat.com/initializer': 'other-job'}
        with self.assertRaisesRegex(RuntimeError, 'Another bootstrap'):
            self.run_bootstrap()
        self.assertFalse(self.vault.initialized)

    def test_resource_version_conflict_prevents_initialization(self):
        original = self.kube.call
        def conflict(path, data=None, method=None):
            if method == 'PUT': raise error(409)
            return original(path, data, method)
        self.kube.call = conflict
        with self.assertRaises(urllib.error.HTTPError):
            self.run_bootstrap()
        self.assertFalse(self.vault.initialized)

    def test_incompatible_mount_is_not_replaced(self):
        self.vault.mounts['secret/'] = {'type': 'kv', 'options': {'version': '1'}}
        with self.assertRaisesRegex(RuntimeError, 'not KV v2'):
            self.run_bootstrap()
        self.assertEqual(self.vault.mounts['secret/']['options']['version'], '1')

    def test_rotated_ca_updates_with_compare_and_set(self):
        self.run_bootstrap()
        self.run_bootstrap(ca='rotated-ca')
        self.assertEqual(self.vault.ca['metadata']['version'], 2)
        self.assertEqual(self.vault.ca['data']['ca-bundle.crt'], 'rotated-ca')

    def test_expired_writer_token_is_replaced(self):
        self.run_bootstrap()
        self.vault.expired_writer = True
        self.vault.calls.clear()
        self.run_bootstrap()
        self.assertIn('/auth/token/create-orphan', [path for path, _ in self.vault.calls])
        self.assertEqual(self.vault.token, 'root-test')


if __name__ == '__main__':
    unittest.main()
