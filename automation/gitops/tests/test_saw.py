import subprocess
import unittest
import json
import importlib.util
import hashlib
import os
import tempfile
from unittest import mock
from pathlib import Path
from urllib.parse import urlparse

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
    def test_isolated_container_governance_is_pinned_and_scoped(self):
        chart = ROOT / 'infra/bootstrap'
        sha = 'b' * 40
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example',
                          'keycloak': {'postgresPassword': 'example'},
                          'governance': {'customInference': {'host': 'model.example', 'port': 443}},
                          'containerGovernance': {'enabled': True, 'namespace': 'saw-container-governance',
                              'revision': sha, 'imageBuildNamespace': 'saw-builds',
                              'values': {'image': PROXY, 'kubernetesGateways': [
                                  {'namespace': 'saw-alice', 'gatewayId': 'alice'}]}}}}
        docs = render(chart, values)
        apps = {d['metadata']['name']: d for d in docs if d['kind'] == 'Application'}
        container_app = apps['saw-container-governance-interceptor']
        self.assertEqual(container_app['spec']['source']['targetRevision'], sha)
        self.assertEqual(container_app['spec']['destination']['namespace'], 'saw-container-governance')
        self.assertEqual(yaml.safe_load(container_app['spec']['source']['helm']['values'])['image'], PROXY)
        self.assertEqual(apps['saw-governance-interceptor']['spec']['destination']['namespace'], 'openshell-agents')
        profiles = [d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'governance-interceptor-extra-profiles']
        self.assertEqual({d['metadata']['namespace'] for d in profiles}, {'openshell-agents', 'saw-container-governance'})
        self.assertEqual(profiles[0]['data'], profiles[1]['data'])
        role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'saw-container-governance-image-pull')
        self.assertEqual(role['rules'][0]['resourceNames'], ['governance-interceptor'])
        values['saw']['containerGovernance']['namespace'] = 'openshell-agents'
        with self.assertRaises(subprocess.CalledProcessError):
            render(chart, values)

    def test_account_job_assigns_dashboard_admin_role(self):
        script = (ROOT / 'tenant/bootstrap/files/saw-create-user.py').read_text()
        posted = []

        class Response:
            def __init__(self, body):
                self.body = json.dumps(body).encode() if body is not None else b''
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body

        def urlopen(request, **kwargs):
            url = request.full_url
            if '/protocol/openid-connect/token' in url:
                return Response({'access_token': 'test-token'})
            if '/users?' in url:
                return Response([{'id': 'user-id'}])
            if '/roles/' in url:
                return Response({'name': url.rsplit('/', 1)[-1]})
            if url.endswith('/role-mappings/realm'):
                posted.extend(json.loads(request.data))
                return Response(None)
            raise AssertionError(url)

        with mock.patch.dict(os.environ, {'SAW_USER': 'user-7kzmd'}), \
             mock.patch('pathlib.Path.read_text', return_value='test-password'), \
             mock.patch('urllib.request.urlopen', side_effect=urlopen):
            exec(script, {})
        self.assertEqual({role['name'] for role in posted}, {'openshell-user', 'openshell-admin'})

    def test_tenant_litellm_seed_and_workspace(self):
        chart = ROOT / 'tenant/bootstrap'
        saw = {'enabled': True, 'userName': 'user-7kzmd', 'clusterDomain': 'test.example',
               'credentialProxyImage': PROXY, 'vmSource': {'dataSource': 'golden'},
               'inferenceHost': 'model.example',
               'account': {'enabled': True, 'password': 'SecureExample1!'},
               'inferenceSeed': {'enabled': True, 'secretData': {'api_key': 'private-key',
                   'url': 'https://model.example/v1', 'model': 'model-a'}}}
        docs = render(chart, {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': saw})
        job = next(d for d in docs if d['kind'] == 'Job' and d['metadata']['name'] == 'saw-user-7kzmd-inference-seed')
        self.assertNotIn('private-key', yaml.safe_dump(job))
        self.assertEqual(job['spec']['template']['spec']['containers'][0]['env'][0]['value'], 'hub/saw-user-7kzmd/inference')
        source = next(d for d in docs if d['kind'] == 'Secret' and d['metadata']['name'] == 'saw-user-7kzmd-inference-input')
        self.assertEqual(source['stringData']['provider'], 'custom-inference')
        account_job = next(d for d in docs if d['kind'] == 'Job' and d['metadata']['name'] == 'saw-user-7kzmd-account')
        self.assertNotIn('SecureExample1!', yaml.safe_dump(account_job))
        users = next(d for d in docs if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-users-7kzmd')
        apps = {d['metadata']['name']: d for d in child(users) if d['kind'] == 'Application'}
        secrets = child(apps['saw-user-7kzmd-secrets'])
        inference = next(d for d in secrets if d['kind'] == 'ExternalSecret' and d['metadata']['name'] == 'inference')
        self.assertEqual(inference['spec']['dataFrom'][0]['extract']['key'], 'secret/data/hub/saw-user-7kzmd/inference')
        self.assertFalse(any(d['metadata']['name'].startswith('web-search') for d in secrets if d['kind'] == 'ExternalSecret'))
        vm_docs = child(apps['saw-user-7kzmd'])
        self.assertTrue(any(d['kind'] == 'Route' and d['metadata']['name'] == 'user-7kzmd-default-notebook-ui' for d in vm_docs))
        proxy = next(d for d in vm_docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'user-7kzmd-credential-proxy-config')
        policy = json.loads(proxy['data']['config.json'])
        self.assertEqual(policy['profiles']['custom-inference'], ['model.example'])
        self.assertTrue(any('custom-inference' in b['providers'] for b in policy['bindings']))
        firewall = next(d for d in vm_docs if d['kind'] == 'EgressFirewall')
        self.assertTrue(any(rule['type'] == 'Allow' and rule['to'].get('dnsName') == 'model.example'
                            for rule in firewall['spec']['egress']))
        saw['inferenceSeed']['secretData']['url'] = 'https://wrong.example/v1'
        with self.assertRaises(subprocess.CalledProcessError):
            render(chart, {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': saw})

    def test_cluster_ca_is_synced_from_vault(self):
        docs = render(ROOT / 'tenant/saw/charts/pattern-secrets', {'clusterCaSecret': 'saw-ingress-ca'})
        secret = next(d for d in docs if d['kind'] == 'ExternalSecret' and d['metadata']['name'] == 'saw-ingress-ca')
        self.assertEqual(secret['spec']['data'][0]['secretKey'], 'ca-bundle.crt')
        self.assertEqual(secret['spec']['data'][0]['remoteRef']['property'], 'ca-bundle.crt')

    def test_infra_opt_in_and_children(self):
        chart = ROOT / 'infra/bootstrap'
        self.assertEqual([x['kind'] for x in render(chart, {})], ['ConfigMap', 'ArgoCD'])
        docs = render(chart, {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'pass: # example'}}})
        apps = {x['metadata']['name']: x for x in docs if x['kind'] == 'Application'}
        self.assertEqual(set(apps), {'saw-vault', 'saw-external-secrets', 'saw-virtualization', 'saw-keycloak', 'saw-governance-policy', 'saw-governance-interceptor'})
        sandbox_docs = render(chart, {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'test-password'}, 'agentSandbox': {'enabled': True}}})
        sandbox = next(x for x in sandbox_docs if x['kind'] == 'Application' and x['metadata']['name'] == 'saw-agent-sandbox')
        self.assertEqual(sandbox['spec']['destination']['namespace'], 'agent-sandbox-system')
        self.assertTrue(yaml.safe_load(sandbox['spec']['source']['helm']['values'])['enabled'])
        portal_docs = render(chart, {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'pass: # example'}, 'portal': {'enabled': True}}})
        portal = next(x for x in portal_docs if x['kind'] == 'Application' and x['metadata']['name'] == 'saw-rhdh')
        self.assertEqual(portal['spec']['destination']['namespace'], 'rhdh')
        portal_values = yaml.safe_load(portal['spec']['source']['helm']['values'])
        self.assertEqual(portal_values['global']['clusterDomain'], 'test.example')
        self.assertEqual(portal_values['global']['vpArgoNamespace'], 'openshift-gitops')
        self.assertEqual(portal_values['rhdh']['namespace'], 'rhdh')
        portal_sub = next(x for x in portal_docs if x['kind'] == 'Subscription' and x['metadata']['name'] == 'rhdh')
        self.assertEqual(portal_sub['metadata']['namespace'], 'rhdh-operator')
        self.assertEqual(portal_sub['spec']['channel'], 'fast-1.10')
        portal_group = next(x for x in portal_docs if x['kind'] == 'OperatorGroup' and x['metadata']['name'] == 'rhdh-operator')
        self.assertFalse(portal_group.get('spec') and portal_group['spec'].get('targetNamespaces'))
        pipeline_sub = next(x for x in portal_docs if x['kind'] == 'Subscription' and x['metadata']['name'] == 'openshift-pipelines-operator-rh')
        self.assertEqual(pipeline_sub['metadata']['namespace'], 'openshift-pipelines')
        self.assertEqual(pipeline_sub['spec']['channel'], 'pipelines-1.24')
        subscriptions = {x['spec']['name']: x['spec']['channel'] for x in docs if x['kind'] == 'Subscription'}
        self.assertEqual(subscriptions, {'kubevirt-hyperconverged': 'stable', 'rhbk-operator': 'stable-v26', 'openshift-external-secrets-operator': 'stable-v1'})
        resources = {name: child(app) for name, app in apps.items()}
        hco = next(d for d in resources['saw-virtualization'] if d['kind'] == 'HyperConverged')
        patch = json.loads(hco['metadata']['annotations']['kubevirt.kubevirt.io/jsonpatch'])
        self.assertEqual(patch, [{'op': 'add', 'path': '/spec/configuration/developerConfiguration/featureGates/-', 'value': 'EnableVirtioFsConfigVolumes'}])
        store = next(d for d in resources['saw-external-secrets'] if d['kind'] == 'ClusterSecretStore')
        self.assertEqual(store['spec']['provider']['vault']['caProvider']['name'], 'saw-vault-service-ca')
        self.assertEqual(store['spec']['provider']['vault']['auth']['kubernetes']['role'], 'hub-role')
        policy = next(d for d in docs if d['kind'] == 'NetworkPolicy' and d['metadata']['name'] == 'saw-allow-vault-service')
        self.assertEqual(policy['spec']['podSelector']['matchLabels'], {'app.kubernetes.io/name': 'external-secrets'})
        egress = policy['spec']['egress'][0]
        self.assertEqual(egress['ports'], [{'protocol': 'TCP', 'port': urlparse(store['spec']['provider']['vault']['server']).port}])
        self.assertEqual(egress['to'][0]['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'], 'vault')
        vault_pod = next(d for d in resources['saw-vault'] if d['kind'] == 'StatefulSet')['spec']['template']
        for key, value in egress['to'][0]['podSelector']['matchLabels'].items():
            self.assertEqual(vault_pod['metadata']['labels'][key], value)

        self.assertTrue(any(d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'saw-vault-service-ca' for d in docs))
        self.assertTrue(any(d['kind'] == 'ClusterSecretStore' and d['spec']['provider']['vault']['server'] == 'https://vault.vault.svc:8200' for d in resources['saw-external-secrets']))
        vault = next(d for d in resources['saw-vault'] if d['kind'] == 'StatefulSet')
        self.assertRegex(vault['spec']['template']['spec']['containers'][0]['image'], r'@sha256:[a-f0-9]{64}$')
        keycloak = next(d for d in resources['saw-keycloak'] if d['kind'] == 'Keycloak')
        self.assertEqual(keycloak['spec']['hostname']['hostname'], 'https://openshell-keycloak-ingress-saw-keycloak.apps.test.example')

        db_secret = next(d for d in resources['saw-keycloak'] if d['kind'] == 'Secret' and d['metadata']['name'] == 'keycloak-db-secret')
        self.assertEqual(db_secret['stringData']['password'], 'pass: # example')
        for docs in resources.values():
            assert_pod_images_pinned(self, docs)

    def test_keycloak_uses_https_for_bare_hostnames(self):
        chart = ROOT / 'tenant/saw/charts/openshell-keycloak'
        for hostname in ['sso.example.test', 'https://sso.example.test']:
            docs = render(chart, {'keycloak': {'hostname': hostname}}, namespace='saw-keycloak')
            kc = next(d for d in docs if d['kind'] == 'Keycloak')
            self.assertEqual(kc['spec']['hostname']['hostname'], 'https://sso.example.test')

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

    def test_tenant_can_select_container_workspace_mode(self):
        saw = {
            'deploymentMode': 'container', 'userName': 'user-7kzmd',
            'clusterDomain': 'test.example',
            'ownerSubject': '11111111-1111-4111-8111-111111111111',
            'registration': 'abcdef0123456789',
            'installationID': '22222222-2222-4222-8222-222222222222',
            'profile': 'data-science',
            'containerSite': {
                'subject': '11111111-1111-4111-8111-111111111111',
                'automaticEnrollment': {
                    'enabled': False,
                    'approvedProfiles': {'data-science': 'a' * 64},
                },
            },
        }
        docs = render(ROOT / 'tenant/bootstrap', {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': saw})
        app = next(d for d in docs if d['kind'] == 'Application')
        values = yaml.safe_load(app['spec']['source']['helm']['values'])
        user = values['users'][0]
        self.assertEqual(user['values']['deployment']['mode'], 'container')
        self.assertEqual(user['vaultPrefix'], 'secret/data/hub/saw-user-7kzmd/abcdef0123456789')
        self.assertNotIn('vmSource', saw)
        self.assertEqual(values['containerSites']['user-7kzmd']['subject'], saw['ownerSubject'])
        child_apps = child(app)
        runtime = next(d for d in child_apps if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-user-7kzmd')
        self.assertTrue(runtime['spec']['source']['path'].endswith('/saw-portal-container'))

    def test_container_inference_seed_uses_registration_scoped_vault_path(self):
        saw = {
            'deploymentMode': 'container', 'userName': 'user-7kzmd', 'clusterDomain': 'test.example',
            'ownerSubject': '11111111-1111-4111-8111-111111111111',
            'registration': 'abcdef0123456789', 'installationID': '22222222-2222-4222-8222-222222222222',
            'profile': 'custom-inference', 'inferenceHost': 'model.example',
            'containerSite': {'subject': '11111111-1111-4111-8111-111111111111',
                              'automaticEnrollment': {'enabled': False}},
            'inferenceSeed': {'enabled': True, 'secretData': {
                'api_key': 'test-key', 'model': 'test-model', 'url': 'https://model.example/v1'}},
        }
        docs = render(ROOT / 'tenant/bootstrap', {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': saw})
        app = next(d for d in docs if d['kind'] == 'Application')
        values = yaml.safe_load(app['spec']['source']['helm']['values'])
        self.assertEqual(values['users'][0]['vaultPrefix'], 'secret/data/hub/saw-user-7kzmd/abcdef0123456789')
        self.assertEqual(values['global']['chartPrefix'], 'automation/gitops/tenant/saw/charts')
        job = next(d for d in docs if d['kind'] == 'Job' and d['metadata']['name'] == 'saw-user-7kzmd-inference-seed')
        env = job['spec']['template']['spec']['containers'][0]['env']
        self.assertEqual(env[0]['value'], 'hub/saw-user-7kzmd/abcdef0123456789/inference')
        saw['registration'] = '../bad'
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'tenant/bootstrap', {'rag': None, 'tenant': {'name': '7kzmd'}, 'saw': saw})

    def test_container_policy_broad_egress_requires_explicit_demo_waiver(self):
        chart = ROOT / 'tenant/saw/charts/saw-runtime-policies'
        fixture = yaml.safe_load((chart / 'tests/container-values.yaml').read_text())
        fixture['network']['egress'][-1]['to'][0]['networks'] = ['0.0.0.0/0', '::/0']
        command = ['helm', 'template', 'demo', str(chart), '--namespace', 'saw-alice', '-f', '-',
                   '--api-versions', 'policy.networking.k8s.io/v1alpha1/AdminNetworkPolicy',
                   '--api-versions', 'admissionregistration.k8s.io/v1/ValidatingAdmissionPolicy']
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run(command, input=yaml.safe_dump(fixture), text=True, capture_output=True, check=True)
        fixture['network']['allowDemoBroadEgress'] = True
        rendered = subprocess.run(command, input=yaml.safe_dump(fixture), text=True, capture_output=True, check=True)
        self.assertIn('0.0.0.0/0', rendered.stdout)

    def test_demo_container_site_renders_foundation_and_component_apps(self):
        site_file = ROOT / 'infra/bootstrap/demo/container-site-zzt2m.yaml'
        site = yaml.safe_load(site_file.read_text())['saw']['portal']['values']['containerSites']['user-8shcw']
        bootstrap = site['stack']['gateway']['values']['kubernetes']['workload']['runtimeImage']
        self.assertIn('/odh-openshell-sandbox@sha256:', bootstrap)
        self.assertNotEqual(bootstrap, site['automaticEnrollment']['image'])
        module_spec = importlib.util.spec_from_file_location('saw_workspace', ROOT / 'tenant/saw/charts/saw-users/files/workspace.py')
        workspace = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(workspace)
        catalog = json.loads((ROOT / 'tenant/saw/charts/saw-users/files/profile-catalog.json').read_text())['profiles']
        user = {'name': 'user-8shcw', 'ownerSubject': site['subject'], 'registration': 'abcdef0123456789',
                'installationID': '22222222-2222-4222-8222-222222222222', 'profiles': ['custom-inference'],
                'vaultPrefix': 'secret/data/hub/saw-user-8shcw/abcdef0123456789', 'pruneOnRemove': True,
                'customInferenceURL': site['customInferenceURL'], 'values': {'deployment': {'mode': 'container'}}}
        defaults = {'global': {'clusterDomain': 'cluster-zzt2m.dyn.redhatworkshops.io',
                               'repoURL': 'https://github.com/rhpds/red-hat-1-quickstarts.git',
                               'targetRevision': site['stack']['gateway']['revision'], 'vpArgoNamespace': 'openshift-gitops',
                               'chartPrefix': 'automation/gitops/tenant/saw/charts', 'webSearch': {'enabled': False}}}
        values = workspace.project_workspace(user, defaults, site, catalog)
        apps = render(ROOT / 'tenant/saw/charts/saw-users', values, namespace='openshell-agents')
        bom = next(d for d in apps if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-user-8shcw-bom')
        profile_map = next(d for d in child(bom) if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'saw-bom-profiles')
        digest = hashlib.sha256(json.dumps(profile_map['data'], sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(digest, site['automaticEnrollment']['approvedProfiles']['custom-inference'])
        runtime = next(d for d in apps if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-user-8shcw')
        foundation = child(runtime)
        components = [d for d in foundation if d['kind'] == 'Application']
        self.assertEqual(len(components), 5)
        self.assertTrue(all(d['spec']['source']['path'].startswith('automation/gitops/tenant/saw/charts/') for d in components))
        self.assertTrue(any(d['kind'] == 'ExternalSecret' and d['metadata']['name'] == 'inference' for d in foundation))
        for component in components:
            source = component['spec']['source']
            rendered = subprocess.run(['helm', 'template', source['helm']['releaseName'], str(ROOT.parents[1] / source['path']),
                            '--namespace', component['spec']['destination']['namespace'], '-f', '-',
                            '--api-versions', 'agents.x-k8s.io/v1beta1/Sandbox',
                            '--api-versions', 'policy.networking.k8s.io/v1alpha1/AdminNetworkPolicy',
                            '--api-versions', 'admissionregistration.k8s.io/v1/ValidatingAdmissionPolicy'],
                           input=yaml.safe_dump(source['helm']['valuesObject']), text=True, capture_output=True, check=True)
            if component['metadata']['name'].endswith('-gateway'):
                self.assertIn('sandbox_runtime_image = "' + bootstrap + '"', rendered.stdout)
            if component['metadata']['name'].endswith('-policy'):
                self.assertIn(bootstrap, rendered.stdout)

    def test_custom_inference_container_request_uses_only_inference_secret(self):
        chart = ROOT / 'tenant/saw/charts/openshell-rhdh/files'
        catalog = json.loads((chart / 'profile-catalog.json').read_text())['profiles']
        self.assertEqual(catalog, json.loads((ROOT / 'tenant/saw/charts/saw-users/files/profile-catalog.json').read_text())['profiles'])
        module_spec = importlib.util.spec_from_file_location('saw_portal', chart / 'portal.py')
        portal = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(portal)
        data = {'deploymentMode': 'container', 'profile': 'custom-inference',
                'inference.api_key': 'test-key', 'inference.url': 'https://model.example/v1',
                'inference.model': 'test-model'}
        with mock.patch.dict(os.environ, {'SAW_DEPLOYMENT_MODES': '["vm", "container"]'}):
            profile, secrets = portal.parse_request(data, catalog)
        self.assertEqual(profile, 'custom-inference')
        self.assertEqual(set(secrets), {'inference'})
        boundary = {'inferenceBaseURL': 'https://model.example/v1', 'allowHosts': ['model.example']}
        self.assertEqual(portal.approved_endpoint(catalog[profile], secrets, boundary), 'https://model.example/v1')
        secrets['inference']['url'] = 'https://other.example/v1'
        with self.assertRaises(portal.PortalError):
            portal.approved_endpoint(catalog[profile], secrets, boundary)

    def test_container_previous_child_checks_configured_chart_prefix(self):
        chart = ROOT / 'tenant/saw/charts/saw-users/files/workspace.py'
        module_spec = importlib.util.spec_from_file_location('saw_workspace_path_test', chart)
        workspace = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(workspace)
        owner = {'name': 'alice', 'installationID': 'install', 'registration': 'registration', 'ownerSubject': 'subject'}
        revision = 'a' * 40
        prefix = 'automation/gitops/tenant/saw/charts'
        values = {'users': [owner], 'global': {'targetRevision': revision}}
        app = {'metadata': {'labels': {'openshell.pattern/owner': 'alice'}, 'ownerReferences': [
            {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'ApplicationSet', 'name': 'portal', 'controller': True}]},
            'spec': {'source': {'path': prefix + '/saw-users', 'targetRevision': revision,
                                'helm': {'values': json.dumps(values)}}}}
        self.assertEqual(workspace.previous_child(app, 'portal', owner, prefix), values)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.previous_child(app, 'portal', owner, 'charts')
        with self.assertRaises(workspace.WorkspaceError):
            workspace.previous_child(app, 'portal', owner, '../charts')

    def test_invalid_identity_and_unpinned_inputs_fail(self):
        base = {'rag': None, 'saw': {'userName': '7kzmd', 'clusterDomain': 'test.example', 'credentialProxyImage': PROXY, 'vmSource': {'dataSource': 'golden'}}}
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'tenant/bootstrap', base)
        base['saw']['userName'] = 'alice'
        base['saw']['credentialProxyImage'] = 'example.invalid/proxy:latest'
        with self.assertRaises(subprocess.CalledProcessError):
            render(ROOT / 'tenant/bootstrap', base)


class SawRefreshTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('SAW_UPSTREAM_SOURCE'), 'Set SAW_UPSTREAM_SOURCE to a local upstream checkout')
    def test_pinned_refresh_reproduces_vendored_files(self):
        current = ROOT / 'tenant/saw'
        ref = json.loads((current / 'source.json').read_text())['commit']
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'saw'
            updater.update(os.environ['SAW_UPSTREAM_SOURCE'], ref, destination)
            def snapshot(directory):
                result = {}
                for path in directory.rglob('*'):
                    if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
                        continue
                    relative = path.relative_to(directory).as_posix()
                    if relative in ('README.md', 'source.json'):
                        continue
                    # The original import removed blank final lines in .helmignore.
                    data = path.read_bytes()
                    result[relative] = data.rstrip(b'\n') if path.name == '.helmignore' else data
                return result
            expected, actual = snapshot(current), snapshot(destination)
            self.assertEqual(actual.keys(), expected.keys())
            for path in expected:
                with self.subTest(path=path):
                    self.assertEqual(actual[path], expected[path])
            updater.update(os.environ['SAW_UPSTREAM_SOURCE'], ref, destination)
            self.assertEqual(snapshot(destination), actual)

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
            files = {'charts/openshift-cnv/templates/hyperconverged.yaml': 'apiVersion: hco.kubevirt.io/v1beta1\nkind: HyperConverged\nmetadata:\n  name: kubevirt-hyperconverged\n  namespace: openshift-cnv\nspec: {}\n',
                     'charts/saw-users/templates/applications.yaml': 'path: "charts/openshell-saw"\n',
                     'charts/openshell-rhdh/templates/applicationset.yaml': 'path: charts/saw-users\n',
                     'charts/openshell-keycloak/values.yaml': 'image: registry.access.redhat.com/ubi9/python-311:latest\n',
                     'charts/openshell-keycloak/templates/postgres.yaml': 'username: {{ .Values.postgres.username }}\npassword: {{ .Values.postgres.password }}\n',
                     'image-builder-charts/helm/example/Chart.yaml': 'name: example\nversion: 0.1.0\n',
                     'overrides/governance-profiles/kustomization.yaml': 'kind: Kustomization\n'}
            patches = json.loads((ROOT / 'saw-patches.json').read_text())
            for patch in patches:
                files[patch['file']] = (ROOT / 'tenant/saw' / patch['file']).read_text()
            # Reconstruct pre-patch files in reverse order: later patches may
            # use context introduced by an earlier compatibility fix.
            for patch in reversed(patches):
                contents = files[patch['file']]
                self.assertEqual(contents.count(patch['new']), 1, patch['file'])
                files[patch['file']] = contents.replace(patch['new'], patch['old'])
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
            for patch in patches:
                self.assertEqual((destination / patch['file']).read_bytes(), (ROOT / 'tenant/saw' / patch['file']).read_bytes())

            for relative in updater.LOCAL_DIRECTORIES:
                local = ROOT / 'tenant/saw' / relative
                for file in local.rglob('*'):
                    if file.is_file():
                        self.assertEqual((destination / file.relative_to(ROOT / 'tenant/saw')).read_bytes(),
                                         file.read_bytes())

            self.assertIn('EnableVirtioFsConfigVolumes', (destination / 'charts/openshift-cnv/templates/hyperconverged.yaml').read_text())
            # Refreshing in place must preserve edits in the single source tree,
            # while respecting local deletions and replacing unowned files.
            marker = destination / updater.LOCAL_DIRECTORIES[0] / 'mcp/local-edit.mjs'
            marker.write_text('// local edit\n')
            (destination / 'obsolete-vendor-file').write_text('remove on refresh\n')
            with mock.patch.object(updater, 'DESTINATION', destination):
                updater.update(source, 'HEAD', destination)
                self.assertEqual(marker.read_text(), '// local edit\n')
                self.assertFalse((destination / 'obsolete-vendor-file').exists())
                marker.unlink()
                updater.update(source, 'HEAD', destination)
            self.assertEqual(snapshot(), before)

            with mock.patch.object(updater, 'DESTINATION', Path(tmp) / 'missing-local-source'):
                with self.assertRaisesRegex(ValueError, 'Missing local SAW directory'):
                    updater.update(source, 'HEAD', destination)
            self.assertEqual(snapshot(), before)

            # An incompatible upstream addition must leave the existing vendor
            # tree intact, even after other patches have been staged.
            for relative in updater.LOCAL_DIRECTORIES:
                with self.subTest(collision=relative):
                    collision = source / relative / 'plugin.json'
                    collision.parent.mkdir(parents=True, exist_ok=True)
                    collision.write_text('different upstream implementation\n')
                    subprocess.run(['git', '-C', str(source), 'add', '-A'], check=True)
                    subprocess.run(['git', '-C', str(source), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'upstream collision'], check=True)
                    with self.assertRaisesRegex(ValueError, 'review the local demo directory'):
                        updater.update(source, 'HEAD', destination)
                    self.assertEqual(snapshot(), before)
                    collision.unlink()

            changed = patches[0]
            (source / changed['file']).write_text('upstream changed the patch context\n')
            subprocess.run(['git', '-C', str(source), 'add', '-A'], check=True)
            subprocess.run(['git', '-C', str(source), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'upstream context change'], check=True)
            with self.assertRaisesRegex(ValueError, 'review the local compatibility patch'):
                updater.update(source, 'HEAD', destination)
            self.assertEqual(snapshot(), before)


@unittest.skipUnless(os.environ.get('AGNOSTICV_CLUSTER_CONFIG') and os.environ.get('AGNOSTICV_TENANT_CONFIG'), 'Set both agnosticv configuration paths')
class SawAgnosticvTests(unittest.TestCase):
    def test_cluster_inference_host_without_tenant_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp = Path(temp)
            output, extra, play = (tmp / name for name in ('values.yaml', 'inputs.json', 'playbook.yaml'))
            play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                'vars_files': [os.environ['AGNOSTICV_CLUSTER_CONFIG']], 'tasks': [
                    {'no_log': True, 'ansible.builtin.copy': {'dest': str(output), 'content': '{{ ocp4_workload_gitops_bootstrap_helm_values | to_nice_yaml }}'}}]}]))
            env = os.environ.copy()
            env.update({'ANSIBLE_LOCAL_TEMP': str(tmp / 'local'), 'ANSIBLE_REMOTE_TEMP': str(tmp / 'remote'), 'ANSIBLE_NOCOLOR': '1'})
            base = {'saw_enabled': True, 'saw_keycloak_db_password': 'test-password',
                    'openshift_cluster_ingress_domain': 'apps.test.example'}
            for overrides, expected in [({'litellm_url': 'https://model.example/v1'}, 'model.example'),
                                        ({'litellm_url': 'https://model.example/', 'saw_inference_host': 'override.example'}, 'override.example'),
                                        ({}, '')]:
                extra.write_text(json.dumps({**base, **overrides}))
                subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', '-e', '@' + str(extra), str(play)],
                               check=True, capture_output=True, text=True, env=env)
                values = yaml.safe_load(output.read_text())
                self.assertEqual(values['saw']['governance']['customInference']['host'], expected)
                docs = render(ROOT / 'infra/bootstrap', values)
                profiles = [d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'governance-interceptor-extra-profiles']
                self.assertEqual(bool(profiles), bool(expected))
                if profiles:
                    self.assertEqual(yaml.safe_load(profiles[0]['data']['custom-inference.yaml'])['endpoints'][0]['host'], expected)

    def test_cluster_and_tenant_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inputs = {'guid': '7kzmd', 'common_password': 'TestPass1234', 'saw_enabled': True, 'output_dir': str(tmp),
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
                    self.assertEqual(values['saw']['governance']['customInference']['host'], 'model.example')
                    self.assertEqual(values['saw']['keycloak']['values']['keycloak']['passwordPolicy'], 'length(12)')
                    keycloak_app = next(d for d in docs if d['kind'] == 'Application' and d['metadata']['name'] == 'saw-keycloak')
                    realm = next(d for d in child(keycloak_app) if d['kind'] == 'KeycloakRealmImport')
                    self.assertEqual(realm['spec']['realm']['passwordPolicy'], 'length(12)')
                    self.assertTrue(any(d['kind'] == 'Job' and d['metadata']['name'] == 'saw-inference-seed' for d in docs))
                else:
                    self.assertEqual(values['saw']['userName'], 'user-7kzmd')
                    self.assertEqual(values['saw']['inferenceHost'], 'model.example')
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['api_key'], 'test-key')
                    self.assertEqual(values['saw']['inferenceSeed']['secretData']['url'], 'https://model.example/v1')
                    self.assertTrue(values['saw']['account']['enabled'])
                    self.assertEqual(values['saw']['account']['password'], inputs['common_password'])
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
