import subprocess
import unittest
import json
import importlib.util
import os
import tempfile
from unittest import mock
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROXY = 'example.invalid/proxy@sha256:' + 'a' * 64
spec = importlib.util.spec_from_file_location('update_saw', ROOT / 'update-saw.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def render(chart, values, release='test', namespace='openshift-gitops'):
    output = subprocess.check_output(['helm', 'template', release, str(chart), '--namespace', namespace, '-f', '-'], input=yaml.safe_dump(values), text=True)
    return [doc for doc in yaml.safe_load_all(output) if isinstance(doc, dict)]


def child(app):
    src = app['spec']['source']
    return render(ROOT.parents[1] / src['path'], yaml.safe_load(src['helm']['values']) or {}, src['helm']['releaseName'], app['spec']['destination']['namespace'])


def assert_pod_images_pinned(test, docs):
    def visit(item):
        if isinstance(item, dict):
            for key, value in item.items():
                if key == 'image' and isinstance(value, str):
                    test.assertRegex(value, r'@sha256:[a-f0-9]{64}$')
                visit(value)
        elif isinstance(item, list):
            for value in item:
                visit(value)
    visit(docs)


class SawIntegrationTests(unittest.TestCase):
    def test_cluster_ca_is_synced_from_vault(self):
        docs = render(ROOT / 'tenant/saw/charts/pattern-secrets', {'clusterCaSecret': 'saw-ingress-ca'})
        secret = next(d for d in docs if d['kind'] == 'ExternalSecret' and d['metadata']['name'] == 'saw-ingress-ca')
        self.assertEqual(secret['spec']['data'][0]['secretKey'], 'ca-bundle.crt')
        self.assertEqual(secret['spec']['data'][0]['remoteRef']['property'], 'ca-bundle.crt')

    def test_infra_opt_in_and_children(self):
        chart = ROOT / 'infra/bootstrap'
        self.assertEqual([x['kind'] for x in render(chart, {})], ['ConfigMap'])
        docs = render(chart, {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'pass: # example'}}})
        apps = {x['metadata']['name']: x for x in docs if x['kind'] == 'Application'}
        self.assertEqual(set(apps), {'saw-vault', 'saw-external-secrets', 'saw-virtualization', 'saw-keycloak', 'saw-governance-policy', 'saw-governance-interceptor'})
        subscriptions = {x['spec']['name']: x['spec']['channel'] for x in docs if x['kind'] == 'Subscription'}
        self.assertEqual(subscriptions, {'kubevirt-hyperconverged': 'stable', 'rhbk-operator': 'stable-v26', 'openshift-external-secrets-operator': 'stable-v1'})
        resources = {name: child(app) for name, app in apps.items()}
        self.assertTrue(any(d['kind'] == 'HyperConverged' for d in resources['saw-virtualization']))
        self.assertTrue(any(d['kind'] == 'ClusterSecretStore' and d['spec']['provider']['vault']['server'] == 'https://vault-vault.apps.test.example' for d in resources['saw-external-secrets']))
        vault = next(d for d in resources['saw-vault'] if d['kind'] == 'StatefulSet')
        self.assertRegex(vault['spec']['template']['spec']['containers'][0]['image'], r'@sha256:[a-f0-9]{64}$')
        self.assertTrue(any(d['kind'] == 'Keycloak' for d in resources['saw-keycloak']))
        db_secret = next(d for d in resources['saw-keycloak'] if d['kind'] == 'Secret' and d['metadata']['name'] == 'keycloak-db-secret')
        self.assertEqual(db_secret['stringData']['password'], 'pass: # example')
        for docs in resources.values():
            assert_pod_images_pinned(self, docs)

    def test_seed_uses_secret_references_and_supports_agnosticv_values(self):
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'test-password'},
                  'governance': {'customInference': {'host': 'model.example', 'port': 443}},
                  'inferenceSeed': {'enabled': True, 'vaultPath': 'hub/saw-alice/inference', 'sourceSecret': 'inference-input',
                                    'vaultTokenSecret': 'vault-writer', 'secretData': {'api_key': 'test-api-key', 'url': 'https://model.example/v1', 'model': 'test-model', 'provider': 'custom-inference'}}}}
        docs = render(ROOT / 'infra/bootstrap', values)
        source = next(d for d in docs if d['kind'] == 'Secret' and d['metadata']['name'] == 'inference-input')
        self.assertEqual(source['stringData']['api_key'], 'test-api-key')
        job = next(d for d in docs if d['kind'] == 'Job')
        spec = job['spec']['template']['spec']
        self.assertNotIn('test-api-key', yaml.safe_dump(spec))
        self.assertEqual({v['secret']['secretName'] for v in spec['volumes'] if 'secret' in v}, {'inference-input', 'vault-writer'})
        self.assertEqual(spec['containers'][0]['env'][0]['value'], 'hub/saw-alice/inference')
        profile = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'governance-interceptor-extra-profiles')
        self.assertEqual(yaml.safe_load(profile['data']['custom-inference.yaml'])['endpoints'][0]['host'], 'model.example')
        captured = {}
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
        def read_file(path):
            return {'/vault-token/token': 'fake-writer-token', '/input/api_key': 'fake-inference-key', '/input/model': 'test-model', '/input/provider': 'custom-inference', '/input/url': 'https://model.example/v1'}[str(path)]
        def post(request, **kwargs):
            captured['request'] = request
            return Response()
        with mock.patch.dict(os.environ, {'VAULT_PATH': 'hub/saw-alice/inference'}), \
             mock.patch('pathlib.Path.read_text', read_file), mock.patch('pathlib.Path.is_file', lambda p: str(p).startswith('/input/')), \
             mock.patch('ssl.create_default_context', return_value=None), mock.patch('urllib.request.urlopen', side_effect=post):
            exec(spec['containers'][0]['args'][0], {})
        request = captured['request']
        self.assertEqual(request.full_url, 'https://vault.vault.svc:8200/v1/secret/data/hub/saw-alice/inference')
        self.assertEqual(json.loads(request.data)['data']['api_key'], 'fake-inference-key')
        self.assertEqual(request.get_header('X-vault-token'), 'fake-writer-token')
        values['saw']['governance']['customInference']['host'] = 'wrong.example'
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'infra/bootstrap', values)
        values['saw']['governance']['customInference']['host'] = 'model.example'
        values['saw']['inferenceSeed']['vaultPath'] = '../bad/inference'
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'infra/bootstrap', values)

    def test_user_apps_point_to_vendored_charts(self):
        values = {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': {'userName': 'user-7kzmd', 'clusterDomain': 'test.example', 'credentialProxyImage': PROXY, 'vmSource': {'dataSource': 'golden'}, 'git': {'revision': 'test-sha'}}}
        app = next(d for d in render(ROOT / 'tenant/bootstrap', values) if d['kind'] == 'Application')
        self.assertEqual(app['metadata']['name'], 'saw-users-7kzmd')
        self.assertEqual(app['spec']['source']['targetRevision'], 'test-sha')
        resources = child(app)
        apps = {x['metadata']['name']: x for x in resources if x['kind'] == 'Application'}
        self.assertEqual(set(apps), {'saw-user-7kzmd', 'saw-user-7kzmd-bom', 'saw-user-7kzmd-secrets'})
        for application in apps.values():
            src = application['spec']['source']
            self.assertTrue(src['path'].startswith('automation/gitops/tenant/saw/charts/'))
            self.assertEqual(src['targetRevision'], 'test-sha')
            self.assertEqual(src['repoURL'], app['spec']['source']['repoURL'])
            self.assertEqual(application['spec']['destination']['namespace'], 'saw-user-7kzmd')
            child(application)
        vm = child(apps['saw-user-7kzmd'])
        assert_pod_images_pinned(self, vm)
        self.assertTrue(any(d['kind'] == 'VirtualMachine' for d in vm))
        proxy = next(d for d in vm if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('credential-proxy'))
        self.assertEqual(proxy['spec']['template']['spec']['containers'][0]['image'], PROXY)

    def test_invalid_identity_and_unpinned_inputs_fail(self):
        base = {'rag': None, 'saw': {'userName': '7kzmd', 'clusterDomain': 'test.example', 'credentialProxyImage': PROXY, 'vmSource': {'dataSource': 'golden'}}}
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'tenant/bootstrap', base)
        base['saw']['userName'] = 'alice'
        base['saw']['credentialProxyImage'] = 'example.invalid/proxy:latest'
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'tenant/bootstrap', base)


class SawRefreshTests(unittest.TestCase):
    def test_refresh_is_repeatable_and_preserves_documentation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, destination = Path(tmp) / 'source', Path(tmp) / 'destination'
            source.mkdir()
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            subprocess.run(['git', '-C', str(source), 'config', 'user.email', 'test@example.invalid'], check=True)
            subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Test'], check=True)
            for name in ('saw-users', 'openshell-saw', 'saw-bom', 'pattern-secrets', 'openshell-keycloak', 'openshift-cnv', 'governance-policy', 'governance-interceptor', 'openshell-rhdh'):
                chart = source / 'charts' / name
                chart.mkdir(parents=True)
                (chart / 'Chart.yaml').write_text(f'name: {name}\nversion: 0.1.0\n')
            files = {'charts/saw-users/templates/applications.yaml': 'path: "charts/openshell-saw"\n',
                     'charts/openshell-rhdh/templates/applicationset.yaml': 'path: charts/saw-users\n',
                     'charts/openshell-keycloak/values.yaml': 'image: registry.access.redhat.com/ubi9/python-311:latest\n',
                     'charts/openshell-keycloak/templates/postgres.yaml': 'username: {{ .Values.postgres.username }}\npassword: {{ .Values.postgres.password }}\n',
                     'image-builder-charts/helm/example/Chart.yaml': 'name: example\nversion: 0.1.0\n',
                     'overrides/governance-profiles/kustomization.yaml': 'kind: Kustomization\n'}
            for name, contents in files.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
            subprocess.run(['git', '-C', str(source), 'add', '-A'], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], check=True)
            destination.mkdir()
            (destination / 'README.md').write_text('local documentation\n')
            updater.update(source, 'HEAD', destination)
            def snapshot():
                return {str(p.relative_to(destination)): p.read_bytes() for p in destination.rglob('*') if p.is_file()}
            before = snapshot()
            self.assertIn('automation/gitops/tenant/saw/charts/', (destination / 'charts/saw-users/templates/applications.yaml').read_text())
            self.assertIn('@sha256:', (destination / 'charts/openshell-keycloak/values.yaml').read_text())
            self.assertEqual((destination / 'README.md').read_text(), 'local documentation\n')
            updater.update(source, 'HEAD', destination)
            self.assertEqual(snapshot(), before)


@unittest.skipUnless(os.environ.get('AGNOSTICV_CLUSTER_CONFIG') and os.environ.get('AGNOSTICV_TENANT_CONFIG'), 'Set both agnosticv configuration paths')
class SawAgnosticvTests(unittest.TestCase):
    def test_cluster_and_tenant_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inputs = {'guid': '7kzmd', 'common_password': 'test-password', 'saw_enabled': True,
                      'saw_inference_seed_enabled': True, 'saw_inference_api_key': 'test-key',
                      'saw_inference_url': 'https://integrate.api.nvidia.com/v1', 'saw_inference_model': 'test-model',
                      'saw_inference_host': 'integrate.api.nvidia.com', 'openshift_cluster_ingress_domain': 'apps.test.example',
                      'saw_credential_proxy_image': PROXY, 'saw_golden_image_datasource': 'golden',
                      'litellm_api_endpoint': 'https://model.example', 'litellm_virtual_key': 'test-key',
                      'ai_quickstart_hugging_face_token': 'test-hf', 'ai_quickstart_tavily_search_key': 'test-tavily'}
            extra = tmp / 'inputs.json'
            extra.write_text(json.dumps(inputs))
            for env_name, chart in [('AGNOSTICV_CLUSTER_CONFIG', 'infra/bootstrap'), ('AGNOSTICV_TENANT_CONFIG', 'tenant/bootstrap')]:
                output = tmp / 'values.yaml'
                showroom = tmp / 'showroom.yaml'
                play = tmp / 'playbook.yaml'
                play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                    'vars_files': [os.environ[env_name]], 'tasks': [
                        {'no_log': True, 'ansible.builtin.copy': {'dest': str(output), 'content': '{{ ocp4_workload_gitops_bootstrap_helm_values | to_nice_yaml }}'}},
                        {'no_log': True, 'when': 'ocp4_workload_showroom_content_ui_config is defined', 'ansible.builtin.copy': {'dest': str(showroom), 'content': '{{ ocp4_workload_showroom_content_ui_config }}'}}]}]))
                env = os.environ.copy()
                env.update({'ANSIBLE_LOCAL_TEMP': str(tmp / 'local'), 'ANSIBLE_REMOTE_TEMP': str(tmp / 'remote'), 'ANSIBLE_NOCOLOR': '1'})
                subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', '-e', '@' + str(extra), str(play)], check=True, capture_output=True, text=True, env=env)
                values = yaml.safe_load(output.read_text())
                self.assertTrue(values['saw']['enabled'])
                docs = render(ROOT / chart, values)
                if env_name == 'AGNOSTICV_CLUSTER_CONFIG':
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['api_key'], 'test-key')
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['provider'], 'nvidia')
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['url'], 'https://integrate.api.nvidia.com/v1')
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['model'], 'test-model')
                    self.assertEqual(values['saw']['clusterDomain'], 'test.example')
                    self.assertEqual(values['saw']['governance']['customInference']['host'], 'integrate.api.nvidia.com')
                    self.assertTrue(any(d['kind'] == 'Job' and d['metadata']['name'] == 'saw-inference-seed' for d in docs))
                else:
                    self.assertEqual(values['saw']['userName'], 'user-7kzmd')
                    self.assertEqual(values['saw']['inferenceHost'], 'integrate.api.nvidia.com')
                    self.assertEqual(values['saw']['values']['defaults']['profiles'], ['data-science'])
                    users = next(d for d in docs if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-users-7kzmd')
                    workspace = next(d for d in child(users) if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-user-7kzmd')
                    routes = {d['metadata']['name']: d['spec'].get('host') for d in child(workspace) if d['kind'] == 'Route'}
                    tabs = {tab['name']: tab.get('url') for tab in yaml.safe_load(showroom.read_text())['tabs']}
                    webui_host = routes['user-7kzmd-webui'] or 'user-7kzmd-webui-' + workspace['spec']['destination']['namespace'] + '.' + inputs['openshift_cluster_ingress_domain']
                    self.assertEqual(tabs['SAW Dashboard'], 'https://' + webui_host)
                    self.assertEqual(tabs['OpenClaw'], 'https://' + routes['user-7kzmd-default-notebook-ui'])
                    inputs['saw_enabled'] = False
                    extra.write_text(json.dumps(inputs))
                    subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', '-e', '@' + str(extra), str(play)], check=True, capture_output=True, text=True, env=env)
                    disabled_tabs = {tab['name'] for tab in yaml.safe_load(showroom.read_text())['tabs']}
                    self.assertFalse({'SAW Dashboard', 'OpenClaw'} & disabled_tabs)


if __name__ == '__main__':
    unittest.main()
