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
    def test_mutable_demo_image_overrides_are_rejected(self):
        for chart, key in [('mailpit', 'image'), ('mattermost', 'image'),
                           ('mattermost', 'postgresImage'), ('radicale', 'image')]:
            result = subprocess.run(['helm', 'template', 'test', str(ROOT / 'infra/saw-demo/charts' / chart),
                                     '--set', key + '=example.invalid/unreviewed:latest'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, chart + ': ' + key)
            self.assertIn('must be pinned by digest', result.stderr)

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
                'inferenceSeed': {'enabled': True, 'secretData': {'api_key': 'synthetic-key', 'url': 'https://model.example/v1', 'model': 'existing-model'}},
                'inferenceHost': 'model.example', 'demo': {'enabled': True, 'provisioningEnabled': True}}}

    def test_setup_is_one_shared_infra_job_without_identity_gateways(self):
        docs = render('infra/bootstrap', {'saw': {'enabled': True, 'clusterDomain': 'test.example',
                      'keycloak': {'postgresPassword': 'example-only'},
                      'demo': {'enabled': True, 'calendarEnabled': True, 'provisioningEnabled': True}}})
        jobs = [d for d in docs if d['kind'] == 'Job' and d['metadata']['name'].startswith('saw-demo')]
        self.assertEqual([d['metadata']['name'] for d in jobs], ['saw-demo-seed'])
        pod = jobs[0]['spec']['template']['spec']
        self.assertEqual(jobs[0]['metadata']['namespace'], 'vault')
        self.assertEqual(pod['containers'][0]['command'], ['python', '/scripts/seed-demo.py', 'seed', '--in-cluster'])
        self.assertTrue(any(v.get('secret', {}).get('secretName') == 'saw-demo-password' for v in pod['volumes']))
        self.assertFalse(any(d['kind'] == 'Deployment' and 'access' in d['metadata']['name'] for d in docs))
        for policy in [d for d in docs if d['kind'] == 'NetworkPolicy' and d['metadata']['name'].startswith('saw-demo-')]:
            peers = policy['spec']['ingress'][0]['from']
            self.assertIn({'namespaceSelector': {'matchLabels': {'policy-group.network.openshift.io/ingress': ''}}}, peers)
            self.assertIn({'namespaceSelector': {'matchLabels': {'policy-group.network.openshift.io/host-network': ''}}}, peers)
        profiles = next(d['data'] for d in docs if d['metadata']['name'] == 'governance-interceptor-extra-profiles')
        for source in ['mailpit', 'calendar']:
            profile = yaml.safe_load(profiles[source + '.yaml'])
            self.assertFalse(profile.get('credentials'))
            self.assertTrue(all(e['access'] == 'read-only' and e['port'] == 443 for e in profile['endpoints']))
        for app in [d for d in docs if d['kind'] == 'Application' and d['metadata']['name'].startswith('saw-demo-')]:
            values = yaml.safe_load(app['spec']['source']['helm']['values'])
            chart = ROOT.parents[1] / app['spec']['source']['path']
            route = next(d for d in render(chart, values) if d['kind'] == 'Route')
            self.assertNotIn('-access', route['spec']['to']['name'])

    def test_tenants_keep_private_inference_and_share_only_demo_chat_credentials(self):
        docs = render('tenant/bootstrap', self.tenant_values())
        self.assertFalse(any(d['kind'] == 'Job' and 'demo' in d['metadata']['name'] for d in docs))
        app = next(d for d in docs if d['kind'] == 'Application')
        values = yaml.safe_load(app['spec']['source']['helm']['values'])
        self.assertEqual(values['defaults']['profiles'], ['demo-assistant'])
        self.assertEqual(values['defaults']['openshellSaw']['sourceReaders']['demoId'], 'rh1')
        child = render('tenant/saw/charts/saw-users', values)
        settings = {d['spec']['source']['path'].rsplit('/', 1)[-1]: yaml.safe_load(d['spec']['source']['helm']['values'])
                    for d in child if d['kind'] == 'Application'}
        self.assertEqual(set(settings['pattern-secrets']['secrets']), {'inference', 'mattermost'})
        secrets = render('tenant/saw/charts/pattern-secrets', settings['pattern-secrets'])
        for name in ['mattermost', 'mattermost-meta']:
            secret = next(d for d in secrets if d['metadata']['name'] == name)
            self.assertEqual(secret['spec']['dataFrom'][0]['extract']['key'], 'secret/data/hub/saw-demo/mattermost')
        inference = next(d for d in secrets if d['metadata']['name'] == 'inference')
        self.assertEqual(inference['spec']['dataFrom'][0]['extract']['key'], 'secret/data/hub/saw-user-test/inference')
        machine = render('tenant/saw/charts/openshell-saw', settings['openshell-saw'])
        proxy = next(d for d in machine if d['kind'] == 'ConfigMap' and d['metadata']['name'].endswith('-credential-proxy-config'))
        policy = json.loads(proxy['data']['config.json'])
        self.assertEqual(policy['profiles']['mattermost'], ['mattermost-ui-openshell-agents.apps.test.example'])
        self.assertEqual({b['secret'] for b in policy['bindings']}, {'inference', 'mattermost'})
        bom = render('tenant/saw/charts/saw-bom', settings['saw-bom'])
        data = next(d['data'] for d in bom if d['kind'] == 'ConfigMap')
        providers = yaml.safe_load(next(v for k,v in data.items() if k.endswith('providers.yaml')))['spec']['providers']
        self.assertEqual({p['name'] for p in providers if p.get('credentialFree')}, {'mailpit', 'calendar'})


if __name__ == '__main__':
    unittest.main()
