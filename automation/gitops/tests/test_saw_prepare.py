import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECTION = ROOT / 'infra/ansible'
ROLE = COLLECTION / 'roles/saw_prepare'
SSH_SCRIPT = (ROLE / 'files/seed_ssh.py').read_text()


class Response(io.BytesIO):
    def __init__(self, value):
        super().__init__(json.dumps(value).encode())

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def run_seed(urlopen):
    original = pathlib.Path.read_text
    def read(path, *args, **kwargs):
        return 'fake-vault-token' if str(path) == '/vault-token/token' else original(path, *args, **kwargs)
    def keygen(args, **kwargs):
        key = pathlib.Path(args[-1])
        key.write_text('test-private-key')
        key.with_suffix('.pub').write_text('ssh-ed25519 test-public-key')
    with mock.patch.dict(os.environ, {'SAW_SSH_VAULT_PATH': 'hub/ssh'}), \
         mock.patch('pathlib.Path.read_text', read), mock.patch('ssl.create_default_context', return_value=None), \
         mock.patch('subprocess.run', side_effect=keygen), mock.patch('urllib.request.urlopen', side_effect=urlopen):
        exec(SSH_SCRIPT, {})


class SawPrepareTests(unittest.TestCase):
    def test_existing_key_is_preserved(self):
        calls = []
        def reply(request, **kwargs):
            calls.append(request)
            return Response({'data': {'data': {'private_key': 'existing', 'public_key': 'existing-public'}}})
        run_seed(reply)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_method(), 'GET')

    def test_absent_key_is_created_once_with_compare_and_set(self):
        requests = []
        def reply(request, **kwargs):
            requests.append(request)
            if request.get_method() == 'GET':
                raise urllib.error.HTTPError(request.full_url, 404, 'missing', {}, None)
            return Response({})
        run_seed(reply)
        self.assertEqual([r.get_method() for r in requests], ['GET', 'POST'])
        payload = json.loads(requests[-1].data)
        self.assertEqual(payload['options']['cas'], 0)
        self.assertEqual(payload['data']['public_key'], 'ssh-ed25519 test-public-key')
        self.assertEqual(payload['data']['private_key'], 'test-private-key')

    def test_incomplete_existing_key_fails_without_overwrite(self):
        calls = []
        def reply(request, **kwargs):
            calls.append(request)
            return Response({'data': {'data': {'public_key': 'existing'}}})
        with self.assertRaises(SystemExit):
            run_seed(reply)
        self.assertEqual(len(calls), 1)

    def test_racing_provisioner_preserves_the_winning_key(self):
        methods = []
        def reply(request, **kwargs):
            methods.append(request.get_method())
            if len(methods) == 1:
                raise urllib.error.HTTPError(request.full_url, 404, 'missing', {}, None)
            if len(methods) == 2:
                raise urllib.error.HTTPError(request.full_url, 400, 'cas conflict', {}, None)
            return Response({'data': {'data': {'private_key': 'winner', 'public_key': 'winner-public'}}})
        run_seed(reply)
        self.assertEqual(methods, ['GET', 'POST', 'GET'])

    def test_mirror_script_uses_pinned_source_and_tls_verification(self):
        script = ROLE / 'files/mirror.sh'
        subprocess.run(['sh', '-n', str(script)], check=True)
        text = script.read_text()
        self.assertIn('--preserve-digests', text)
        self.assertIn('--dest-tls-verify=true', text)
        self.assertIn('--password-stdin', text)
        self.assertNotIn('--dest-creds=', text)

    def test_git_subdirectory_collection_install_and_syntax(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp = pathlib.Path(temp)
            repo = tmp / 'repo'
            target = repo / 'automation/gitops/infra/ansible'
            target.parent.mkdir(parents=True)
            shutil.copytree(COLLECTION, target)
            for cmd in (['git', 'init', '-q', str(repo)], ['git', '-C', str(repo), 'config', 'user.name', 'Test'],
                        ['git', '-C', str(repo), 'config', 'user.email', 'test@example.invalid'], ['git', '-C', str(repo), 'add', '-A'],
                        ['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture']):
                subprocess.run(cmd, check=True)
            requirements = tmp / 'requirements.yaml'
            requirements.write_text(yaml.safe_dump({'collections': [{'name': f'file://{repo}#/automation/gitops/infra/ansible', 'type': 'git', 'version': 'HEAD'}]}))
            destination = tmp / 'collections'
            destination.mkdir()
            env = os.environ.copy()
            env.update({'ANSIBLE_LOCAL_TEMP': str(tmp / 'ansible-tmp'), 'ANSIBLE_REMOTE_TEMP': str(tmp / 'ansible-remote'), 'ANSIBLE_COLLECTIONS_PATH': str(destination), 'ANSIBLE_NOCOLOR': '1'})
            subprocess.run(['ansible-galaxy', 'collection', 'install', '-r', str(requirements), '-p', str(destination), '--no-deps'], env=env, check=True, capture_output=True, text=True)
            installed = destination / 'ansible_collections/rhpds/quickstarts/roles/saw_prepare'
            self.assertTrue((installed / 'tasks/provision.yml').exists())
            play = tmp / 'playbook.yaml'
            play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'roles': ['rhpds.quickstarts.saw_prepare']}]))
            subprocess.run(['ansible-playbook', '-i', 'localhost,', '--syntax-check', str(play)], env=env, check=True, capture_output=True, text=True)
            play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'tasks': [{'import_tasks': str(installed / 'tasks/provision.yml')}]}]))
            subprocess.run(['ansible-playbook', '-i', 'localhost,', '--syntax-check', str(play)], env=env, check=True, capture_output=True, text=True)
            variables = yaml.safe_load((installed / 'defaults/main.yml').read_text())
            variables.update({'role_path': str(installed), '_saw_ssh_job': 'saw-ssh-seed-test', '_saw_mirror_job': 'saw-mirror-test',
                              '_saw_registry_destination': 'registry.example/openshell-agents/gateway:fixed', 'saw_prepare_mirror_source_secret': ''})
            play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False, 'vars': variables,
                'tasks': [{'ansible.builtin.template': {'src': str(installed / 'templates' / name), 'dest': str(tmp / name[:-3])}}
                          for name in ('ssh-job.yaml.j2', 'mirror-job.yaml.j2')]}]))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(play)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ssh = yaml.safe_load((tmp / 'ssh-job.yaml').read_text())
            mirror = yaml.safe_load((tmp / 'mirror-job.yaml').read_text())
            self.assertEqual(ssh['spec']['template']['spec']['volumes'][-1]['emptyDir']['medium'], 'Memory')
            self.assertIn('ssh-keygen', ssh['spec']['template']['spec']['containers'][0]['args'][0])
            self.assertEqual(mirror['spec']['template']['spec']['securityContext']['runAsUser'], 1001)
            self.assertIn('--preserve-digests', mirror['spec']['template']['spec']['containers'][0]['args'][0])

    def test_role_orchestration_with_mock_kubernetes(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp = pathlib.Path(temp)
            collection = tmp / 'collections/ansible_collections/rhpds/quickstarts'
            collection.parent.mkdir(parents=True)
            shutil.copytree(COLLECTION, collection)
            plugins = tmp / 'collections/ansible_collections/kubernetes/core/plugins/modules'
            plugins.mkdir(parents=True)
            stub = '''#!/usr/bin/python
from ansible.module_utils.basic import AnsibleModule
import json, os
module = AnsibleModule(argument_spec=dict(api_version=dict(type='str'), kind=dict(type='str'), name=dict(type='str'), namespace=dict(type='str'), state=dict(type='str'), definition=dict(type='dict'), template=dict(type='str')))
args = module.params
info = os.path.basename(__file__).startswith('AnsiballZ_k8s_info') or args.get('kind') is not None
with open(os.environ['SAW_TEST_EVENTS'], 'a') as out:
    out.write(json.dumps({'info': info, 'kind': args.get('kind'), 'template': args.get('template')}) + '\\n')
digest = 'sha256:eaf603d12d763c7154c04fcb78b8cae8cebfc3bdf25a155c63adfa6f74e7d31d'
if info:
    kind = args['kind']
    if kind == 'Secret': resources = [{'data': {'token': 'fake'}}]
    elif kind == 'Job': resources = [{'status': {'succeeded': 1}}]
    elif kind == 'Application': resources = [{'status': {'health': {'status': 'Healthy'}, 'sync': {'status': 'Synced'}}}]
    elif kind == 'ImageStreamTag': resources = [{'image': {'metadata': {'name': digest}}}] if os.path.exists(os.environ['SAW_TEST_MIRRORED']) or os.environ.get('SAW_TEST_EXISTS') == '1' else []
    else: resources = [{}]
    module.exit_json(changed=False, resources=resources)
if (args.get('template') or '').endswith('mirror-job.yaml.j2'):
    open(os.environ['SAW_TEST_MIRRORED'], 'w').close()
module.exit_json(changed=True)
'''
            for name in ('k8s.py', 'k8s_info.py'):
                (plugins / name).write_text(stub)
            play = tmp / 'playbook.yaml'
            play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                                             'vars': {'saw_enabled': True, 'saw_prepare_retries': 2, 'saw_prepare_delay': 0},
                                             'roles': ['rhpds.quickstarts.saw_prepare']}]))
            env = os.environ.copy()
            env.update({'ANSIBLE_LOCAL_TEMP': str(tmp / 'local'), 'ANSIBLE_REMOTE_TEMP': str(tmp / 'remote'),
                        'ANSIBLE_COLLECTIONS_PATH': str(tmp / 'collections'), 'ANSIBLE_NOCOLOR': '1',
                        'SAW_TEST_EVENTS': str(tmp / 'events'), 'SAW_TEST_MIRRORED': str(tmp / 'mirrored')})
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(play)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            events = [json.loads(line) for line in (tmp / 'events').read_text().splitlines()]
            self.assertTrue(any((e['template'] or '').endswith('ssh-job.yaml.j2') for e in events))
            self.assertTrue(any((e['template'] or '').endswith('mirror-job.yaml.j2') for e in events))
            (tmp / 'events').write_text('')
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(play)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            events = [json.loads(line) for line in (tmp / 'events').read_text().splitlines()]
            self.assertFalse(any((e['template'] or '').endswith('mirror-job.yaml.j2') for e in events))


@unittest.skipUnless(os.environ.get('AGNOSTICV_CLUSTER_CONFIG') and os.environ.get('AGNOSTICV_TENANT_CONFIG'), 'Set both agnosticv configuration paths')
class SawPrepareAgnosticvTests(unittest.TestCase):
    def test_collection_order_and_matching_mirror_digest(self):
        cluster = pathlib.Path(os.environ['AGNOSTICV_CLUSTER_CONFIG'])
        tenant = pathlib.Path(os.environ['AGNOSTICV_TENANT_CONFIG'])
        config = yaml.safe_load(cluster.read_text())
        workloads = config['workloads']
        self.assertEqual(workloads.index('rhpds.quickstarts.saw_prepare'), workloads.index('agnosticd.core_workloads.ocp4_workload_gitops_bootstrap') + 1)
        self.assertTrue(any(c['name'].endswith('#/automation/gitops/infra/ansible') and c['type'] == 'git' for c in config['requirements_content']['collections']))
        with tempfile.TemporaryDirectory() as temp:
            tmp = pathlib.Path(temp)
            inputs = {'saw_enabled': True, 'guid': '7kzmd', 'common_password': 'test-password',
                      'openshift_cluster_ingress_domain': 'apps.test.example',
                      'litellm_api_endpoint': 'https://model.example', 'litellm_virtual_key': 'test-key',
                      'ai_quickstart_hugging_face_token': 'test-hf', 'ai_quickstart_tavily_search_key': 'test-tavily'}
            extra = tmp / 'inputs.json'
            extra.write_text(json.dumps(inputs))
            result = tmp / 'out.yaml'
            play = tmp / 'playbook.yaml'
            env = os.environ.copy()
            env.update({'ANSIBLE_LOCAL_TEMP': str(tmp / 'local'), 'ANSIBLE_REMOTE_TEMP': str(tmp / 'remote'), 'ANSIBLE_NOCOLOR': '1'})
            outputs = []
            for path, expression in ((cluster, "{'source': saw_golden_image_source, 'retries': ocp4_workload_gitops_bootstrap_health_retries, 'wait': ocp4_workload_gitops_bootstrap_application_wait}"),
                                     (tenant, "{'source': saw_golden_image_source, 'saw': ocp4_workload_gitops_bootstrap_helm_values.saw}")):
                play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False, 'vars_files': [str(path)],
                    'tasks': [{'no_log': True, 'ansible.builtin.copy': {'dest': str(result), 'content': '{{ ' + expression + ' | to_nice_yaml }}'}}]}]))
                subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', '-e', '@' + str(extra), str(play)], check=True, capture_output=True, text=True, env=env)
                outputs.append(yaml.safe_load(result.read_text()))
            cluster_values, tenant_values = outputs
            self.assertEqual(cluster_values['source'], tenant_values['source'])
            self.assertEqual(int(cluster_values['retries']), 1)
            self.assertFalse(cluster_values['wait'])
            self.assertEqual(tenant_values['saw']['vmSource']['registryURL'], 'docker://image-registry.openshift-image-registry.svc:5000/openshell-agents/openshell-gateway@' + cluster_values['source'].split('@')[-1])


if __name__ == '__main__':
    unittest.main()
