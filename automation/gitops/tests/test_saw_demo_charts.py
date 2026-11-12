"""Render shared demo charts and the tenant provisioning chain."""

import json
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(chart, values):
    text = subprocess.check_output(
        ['helm', 'template', 'saw-demo', str(ROOT / chart), '--namespace', 'openshell-agents', '-f', '-'],
        input=yaml.safe_dump(values),
        text=True,
    )
    return [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]


class DemoChartTests(unittest.TestCase):
    def test_demo_https_routes_and_profiles_share_exact_hosts(self):
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example',
                         'keycloak': {'postgresPassword': 'example-only'},
                         'demo': {'enabled': True, 'calendarEnabled': True}}}
        docs = render(ROOT / 'infra/bootstrap', values)
        profiles = next(d['data'] for d in docs if d['kind'] == 'ConfigMap'
                        and d['metadata']['name'] == 'governance-interceptor-extra-profiles')
        for service, profile in [('mailpit', 'mailpit'), ('mattermost', 'mattermost'), ('radicale', 'calendar')]:
            app = next(d for d in docs if d['metadata']['name'] == 'saw-demo-' + service)
            chart_values = yaml.safe_load(app['spec']['source']['helm'].get('values', '{}'))
            chart = ROOT.parents[1] / app['spec']['source']['path']
            routes = [d for d in render(chart, chart_values) if d['kind'] == 'Route']
            self.assertEqual(len(routes), 1)
            route = routes[0]['spec']
            host = service + '-ui-openshell-agents.apps.test.example'
            self.assertEqual(route['host'], host)
            self.assertEqual(route['tls'], {'termination': 'edge', 'insecureEdgeTerminationPolicy': 'Redirect'})
            endpoints = yaml.safe_load(profiles[profile + '.yaml'])['endpoints']
            self.assertIn((host, 443), [(e['host'], e['port']) for e in endpoints])
            self.assertFalse(any(e['port'] in (8025, 8065, 5232) for e in endpoints))
            # Route activation must not restart pods with ephemeral source data.
            deployments = lambda items: [d for d in items if d['kind'] == 'Deployment']
            self.assertEqual(deployments(render(chart, {})),
                             deployments(render(chart, chart_values)))

    def test_demo_profiles_are_opt_in_and_preserve_inference(self):
        chart = ROOT / 'infra/bootstrap'
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example',
                         'keycloak': {'postgresPassword': 'example-only'},
                         'governance': {'customInference': {'host': 'model.example'}}}}
        def profiles():
            docs = render(chart, values)
            return next(d['data'] for d in docs if d['kind'] == 'ConfigMap'
                        and d['metadata']['name'] == 'governance-interceptor-extra-profiles')
        self.assertEqual(set(profiles()), {'custom-inference.yaml'})
        values['saw']['demo'] = {'enabled': True}
        result = profiles()
        self.assertEqual(set(result), {'custom-inference.yaml', 'mailpit.yaml', 'mattermost.yaml'})
        self.assertEqual(yaml.safe_load(result['custom-inference.yaml'])['endpoints'][0]['host'], 'model.example')
        values['saw']['demo']['calendarEnabled'] = True
        self.assertIn('calendar.yaml', profiles())
        values['saw']['demo']['enabled'] = 'True'
        self.assertEqual(set(profiles()), {'custom-inference.yaml', 'mailpit.yaml', 'mattermost.yaml', 'calendar.yaml'})
        values['saw']['governance']['customInference']['host'] = ''
        self.assertEqual(set(profiles()), {'mailpit.yaml', 'mattermost.yaml', 'calendar.yaml'})

    def test_shared_services_are_opt_in_and_track_the_infra_revision(self):
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example',
                         'git': {'revision': 'feat/saw-personal-assistant'},
                         'keycloak': {'postgresPassword': 'example-only'}}}
        def docs():
            return render(ROOT / 'infra/bootstrap', values)
        self.assertFalse(any(d['metadata']['name'].startswith('saw-demo-') for d in docs()))
        values['saw']['demo'] = {'enabled': True}
        apps = [d for d in docs() if d['kind'] == 'Application' and d['metadata']['name'].startswith('saw-demo-')]
        self.assertEqual({d['metadata']['name'] for d in apps}, {'saw-demo-mailpit', 'saw-demo-mattermost', 'saw-demo-radicale'})
        for app in apps:
            self.assertEqual(app['spec']['source']['targetRevision'], 'feat/saw-personal-assistant')
            self.assertEqual(app['spec']['destination']['namespace'], 'openshell-agents')
            service = app['metadata']['name'].removeprefix('saw-demo-')
            self.assertEqual(app['spec']['source']['path'], 'automation/gitops/infra/saw-demo/charts/' + service)
        bindings = [d for d in docs() if d['kind'] == 'RoleBinding']
        binding = next(d for d in bindings if d['metadata']['name'] == 'saw-demo-anyuid')
        self.assertEqual(binding['subjects'], [{'kind': 'ServiceAccount', 'name': 'saw-demo', 'namespace': 'openshell-agents'}])

    def test_demo_charts_use_pinned_images_and_explicit_privileged_account(self):
        for name in ('mailpit', 'mattermost', 'radicale'):
            with self.subTest(chart=name):
                docs = render(ROOT / 'infra/saw-demo/charts' / name, {})
                self.assertFalse(any(d['kind'] == 'Route' for d in docs))
                for doc in docs:
                    if doc['kind'] == 'Deployment':
                        pod = doc['spec']['template']['spec']
                        if name != 'mailpit':
                            self.assertEqual(pod['serviceAccountName'], 'saw-demo')
                        for container in pod.get('containers', []) + pod.get('initContainers', []):
                            self.assertRegex(container['image'], r'@sha256:[a-f0-9]{64}$')

    def test_tenant_demo_egress_preserves_existing_rules_and_policy_mode(self):
        existing = {
            'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'models'}}}],
            'ports': [{'protocol': 'TCP', 'port': 8000}],
        }
        values = {
            'rag': None,
            'saw': {
                'enabled': True,
                'userName': 'user-test',
                'clusterDomain': 'test.example',
                'credentialProxyImage': 'example.invalid/proxy@sha256:' + 'a' * 64,
                'vmSource': {'dataSource': 'golden'},
                'values': {
                    'defaults': {
                        'openshellSaw': {
                            'egress': {'extraAllow': ['model.example']},
                            'networkPolicy': {'enabled': True, 'extraEgress': [existing]},
                        }
                    }
                },
            },
        }

        def settings():
            docs = render(ROOT / 'tenant/bootstrap', values)
            app = next(d for d in docs if d['kind'] == 'Application')
            return yaml.safe_load(app['spec']['source']['helm']['values'])['defaults']['openshellSaw']

        self.assertEqual(settings()['networkPolicy']['extraEgress'], [existing])
        values['saw']['demo'] = {'enabled': True}
        config = settings()
        result = config['networkPolicy']
        self.assertTrue(result['enabled'])
        self.assertEqual(result['extraEgress'], [existing])
        self.assertEqual(
            set(config['egress']['extraAllow']),
            {'model.example'}
            | {name + '-ui-openshell-agents.apps.test.example' for name in ('mailpit', 'mattermost', 'radicale')},
        )
        values['saw']['values']['defaults']['openshellSaw']['networkPolicy']['enabled'] = False
        self.assertFalse(settings()['networkPolicy']['enabled'])


class DemoProvisioningTests(unittest.TestCase):
    def tenant_values(self):
        return {'rag': None, 'saw': {'enabled': True, 'userName': 'user-test', 'clusterDomain': 'test.example',
                'credentialProxyImage': 'example.invalid/proxy@sha256:' + 'a' * 64, 'vmSource': {'dataSource': 'golden'},
                'account': {'enabled': True, 'password': 'ProvisionedPassword123!'},
                'inferenceSeed': {'enabled': True, 'secretData': {'api_key': 'synthetic-key', 'url': 'https://model.example/v1', 'model': 'existing-model'}},
                'inferenceHost': 'model.example', 'demo': {'enabled': True, 'provisioningEnabled': True}}}

    def test_tenant_job_uses_provisioned_identity_and_secret_mount(self):
        docs = render('tenant/bootstrap', self.tenant_values())
        job = next((d for d in docs if d['kind'] == 'Job' and d['metadata']['name'] == 'saw-user-test-demo-seed'), None)
        self.assertIsNotNone(job, 'tenant demo seed Job must be rendered')
        self.assertEqual(job['metadata']['namespace'], 'vault')
        pod = job['spec']['template']['spec']
        container = pod['containers'][0]
        self.assertIn({'name': 'SAW_USER', 'value': 'user-test'}, container['env'])
        self.assertNotIn('ProvisionedPassword123!', str(container))
        self.assertTrue(any(v.get('secret', {}).get('secretName') == 'saw-user-test-demo-input' for v in pod['volumes']))
        self.assertEqual(job['metadata']['annotations']['argocd.argoproj.io/hook'], 'Sync')
        rules = next(d['rules'] for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'saw-user-test-demo-seed')
        self.assertTrue(all(r.get('resourceNames') for r in rules))

    def test_generated_bom_and_proxy_attach_all_sources_without_manual_channel_id(self):
        docs = render('tenant/bootstrap', self.tenant_values())
        app = next(d for d in docs if d['kind'] == 'Application')
        values = yaml.safe_load(app['spec']['source']['helm']['values'])
        self.assertEqual(values['defaults']['profiles'], ['demo-assistant'])
        self.assertEqual(values['defaults']['openshellSaw']['sourceReaders']['tenantUser'], 'user-test')
        self.assertTrue(values['defaults']['openshellSaw']['sourceReaders']['enabled'])
        child = render('tenant/saw/charts/saw-users', values)
        settings = {
            d['spec']['source']['path'].rsplit('/', 1)[-1]: yaml.safe_load(d['spec']['source']['helm']['values'])
            for d in child
            if d['kind'] == 'Application'
        }
        self.assertEqual(
            set(settings['pattern-secrets']['secrets']), {'inference', 'mailpit', 'calendar', 'mattermost'}
        )
        bindings = settings['openshell-saw']['credentialProxy']['secrets']
        for source in ['mailpit', 'calendar', 'mattermost']:
            self.assertIn({'name': source, 'key': 'api_key', 'providers': [source]}, bindings)
        machine = render('tenant/saw/charts/openshell-saw', settings['openshell-saw'])
        proxy = next(
            d
            for d in machine
            if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith('-credential-proxy-config')
        )
        policy = json.loads(proxy['data']['config.json'])
        for source, service in [('mailpit', 'mailpit'), ('mattermost', 'mattermost'), ('calendar', 'radicale')]:
            self.assertEqual(policy['profiles'].get(source), [service + '-ui-openshell-agents.apps.test.example'])
        bad = dict(settings['openshell-saw'])
        bad['egress'] = {'extraAllow': ['model.example']}
        denied = subprocess.run(
            ['helm', 'template', 'test', str(ROOT / 'tenant/saw/charts/openshell-saw'), '-f', '-'],
            input=yaml.safe_dump(bad),
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('demo credential hosts must also be allowed', denied.stderr)
        bom = render('tenant/saw/charts/saw-bom', settings['saw-bom'])
        data = next(d['data'] for d in bom if d['kind'] == 'ConfigMap')
        providers = yaml.safe_load(next(v for k, v in data.items() if k.endswith('providers.yaml')))['spec'][
            'providers'
        ]
        self.assertEqual({p['name'] for p in providers}, {'custom-inference', 'mailpit', 'mattermost', 'calendar'})
        sandbox = yaml.safe_load(next(v for k, v in data.items() if k.endswith('sandbox.yaml')))['spec']['sandboxes'][0]
        self.assertTrue({'mailpit', 'mattermost', 'calendar'} <= set(sandbox['providers']))

    def test_infra_authenticated_routes_and_readonly_profiles_have_no_backend_bypass(self):
        values = {'saw': {'enabled': True, 'clusterDomain': 'test.example', 'keycloak': {'postgresPassword': 'example-only'},
                          'demo': {'enabled': True, 'calendarEnabled': True, 'provisioningEnabled': True}}}
        docs = render('infra/bootstrap', values)
        names = {(d['kind'],d['metadata']['name']):d for d in docs}
        self.assertIn(('Job','saw-demo-admin'), names)
        for service in ['mailpit', 'radicale']:
            app = names['Application', 'saw-demo-' + service]
            child_values = yaml.safe_load(app['spec']['source']['helm']['values'])
            chart = ROOT.parents[1] / app['spec']['source']['path']
            route = next(d for d in render(chart, child_values) if d['kind'] == 'Route')
            self.assertEqual(route['spec']['to']['name'], 'saw-demo-' + service + '-access')
            self.assertIn(('NetworkPolicy','saw-demo-' + service + '-backend'), names)
        profiles = names['ConfigMap','governance-interceptor-extra-profiles']['data']
        for source in ['mailpit','calendar']:
            profile = yaml.safe_load(profiles[source + '.yaml'])
            self.assertEqual(profile['credentials'][0]['auth_style'], 'header')
            self.assertEqual(profile['credentials'][0]['header_name'], 'authorization')
            self.assertEqual(len(profile['endpoints']),1)
            self.assertEqual(profile['endpoints'][0]['access'], 'read-only')

    def test_provisioning_requires_the_existing_lab_account(self):
        values = self.tenant_values()
        values['saw']['account']['enabled'] = False
        result = subprocess.run(['helm','template','test',str(ROOT/'tenant/bootstrap'),'-f','-'],input=yaml.safe_dump(values),text=True,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('saw.account.enabled',result.stderr)


if __name__ == '__main__':
    unittest.main()
