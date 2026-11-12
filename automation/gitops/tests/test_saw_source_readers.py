import importlib.util
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'tenant/saw/charts/openshell-saw/files/installer/apply_bom.py'
spec = importlib.util.spec_from_file_location('saw_source_installer', PATH)
installer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = installer
spec.loader.exec_module(installer)


class SourceReaderInstallerTests(unittest.TestCase):
    def test_source_tools_and_tool_gate_behavior(self):
        result = subprocess.run(
            [
                'node',
                '--test',
                '--test-isolation=none',
                str(ROOT / 'tests/test_saw_source_readers.mjs'),
                str(PATH.parent / 'tool-gate.test.mjs'),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rendered_installer_is_self_contained_and_covers_javascript_assets(self):
        rendered = subprocess.check_output(
            [
                'helm',
                'template',
                'test',
                str(PATH.parents[2]),
                '--set',
                'global.clusterDomain=test.example',
                '--set',
                'networkPolicy.enabled=false',
                '--set',
                'credentialProxy.image=example.invalid/proxy@sha256:' + 'a' * 64,
                '--show-only',
                'templates/configmap-installer.yaml',
            ],
            text=True,
        )
        data = yaml.safe_load(rendered)['data']
        # The existing golden image verifies apply_bom.py. Do not introduce
        # runtime reads of new, uncovered executable files from the ConfigMap.
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'apply_bom.py'
            script.write_text(data['apply_bom.py'])
            result = subprocess.check_output(
                [
                    sys.executable,
                    '-B',
                    '-c',
                    'import json, runpy, sys; ns = runpy.run_path(sys.argv[1]); '
                    'print(json.dumps([ns["_SOURCE_READERS_PREFLIGHT"], '
                    'ns["_SOURCE_READERS_MODULE"].decode("utf-8")]))',
                    str(script),
                ],
                text=True,
            )
        assets = ['source-readers-preflight.cjs', 'source-readers.mjs']
        self.assertEqual(json.loads(result), [(PATH.parent / name).read_text(encoding='utf-8') for name in assets])
        self.assertTrue(set(assets).isdisjoint(data))

    def test_preflight_prevents_channel_autoinstall_and_preserves_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / '.openclaw/openclaw.json'
            config.parent.mkdir()
            before = {'tools': {'profile': 'full'}, 'plugins': {'entries': {
                'saw-tool-gate': {'enabled': True}}}, 'channels': {'slack': {'enabled': False}}}
            config.write_text(json.dumps(before))
            script = installer._SOURCE_READERS_PREFLIGHT.replace('/sandbox', directory)
            for _ in range(2):
                subprocess.run(['node', '-e', script], check=True, capture_output=True)
            after = json.loads(config.read_text())
            self.assertFalse(after['channels'].pop('mattermost')['enabled'])
            self.assertFalse(after['plugins']['entries'].pop('mattermost')['enabled'])
            self.assertEqual(after, before)

    def test_tenant_reader_opt_in_is_scoped_and_requires_an_assigned_channel(self):
        values = {
            'rag': None,
            'saw': {
                'enabled': True,
                'userName': 'user-test',
                'clusterDomain': 'test.example',
                'credentialProxyImage': 'example.invalid/proxy@sha256:' + 'a' * 64,
                'vmSource': {'dataSource': 'golden'},
                'demo': {'enabled': True, 'readersEnabled': True, 'channelId': 'a' * 26, 'demoId': 'rh1'},
            },
        }
        command = ['helm', 'template', 'test', str(ROOT / 'tenant/bootstrap'), '-f', '-']
        output = subprocess.check_output(command, input=yaml.safe_dump(values), text=True)
        app = next(d for d in yaml.safe_load_all(output) if d and d['kind'] == 'Application')
        settings = yaml.safe_load(app['spec']['source']['helm']['values'])['defaults']['openshellSaw']['sourceReaders']
        self.assertEqual(settings, {'enabled': True, 'channelId': 'a' * 26, 'demoId': 'rh1'})
        values['saw']['demo']['channelId'] = ''
        result = subprocess.run(command, input=yaml.safe_dump(values), text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('saw.demo.channelId', result.stderr)

    def test_source_tool_configuration_is_idempotent_and_restores_previous_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / '.openclaw/openclaw.json'
            source = root / '.saw/trusted/source-readers/config.json'
            config.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            before = {'profile': 'full', 'allow': ['read']}
            config.write_text(json.dumps({'tools': before}))
            source.write_text('{"enabled": true}')
            script = installer._TOOL_GATE_CONFIG.replace('/sandbox', str(root))
            for _ in range(2):
                subprocess.run(['node', '-e', script], check=True, capture_output=True)
                self.assertEqual(json.loads(config.read_text())['tools']['allow'],
                                 ['saw_read_email', 'saw_read_chat', 'saw_read_calendar', 'saw_save_report', 'saw_upload_summary'])
                self.assertTrue(json.loads(config.read_text())['plugins']['entries']['saw-source-readers']
                                ['hooks']['allowConversationAccess'])
            # A disable directly after upgrading must also recognize the old managed list.
            cfg = json.loads(config.read_text())
            cfg['tools']['allow'] = ['saw_read_email', 'saw_read_chat', 'saw_read_calendar']
            config.write_text(json.dumps(cfg))
            source.write_text('{"enabled": false}')
            subprocess.run(['node', '-e', script], check=True, capture_output=True)
            self.assertEqual(json.loads(config.read_text())['tools'], before)

    def test_trusted_bundle_installs_separate_fixed_scope_plugin(self):
        applier = installer.ProfileApplier.__new__(installer.ProfileApplier)
        applier.cfg = {'dashboard': {'owner': 'user-test'}, 'ownerSubject': 'subject-test',
                       'sourceReaders': {'enabled': True, 'clusterDomain': 'test.example',
                                         'demoId': 'rh1', 'channelId': 'a' * 26}}
        tree, _, _, policy_hash = applier.tool_gate_bundle(installer.Workspace(name='default'),
                                                        installer.Sandbox(name='notebook'))
        self.assertIn('source-readers/index.js', tree.keys())
        manifest = json.loads(tree['source-readers/openclaw.plugin.json'][0])
        self.assertEqual(manifest['contracts']['tools'],
                         ['saw_read_email', 'saw_read_chat', 'saw_read_calendar', 'saw_save_report', 'saw_upload_summary'])
        self.assertEqual(manifest['hooks'], ['before_prompt_build'])
        self.assertEqual(tree['source-readers/source-readers.mjs'][0], installer._SOURCE_READERS_MODULE)
        self.assertEqual(json.loads(tree['source-readers/config.json'][0]), applier.cfg['sourceReaders'])
        self.assertIn(policy_hash.encode(), tree['plugin/index.js'][0])
        self.assertIn(b'defaultAction: deny', tree['tool-actions.yaml'][0])

    def test_cluster_and_installer_ship_the_same_tool_policy(self):
        # Behavioral allow/deny checks run in tool-gate.test.mjs; the cluster
        # and signed installer must ship the same policy.
        self.assertEqual(
            (PATH.parent / 'tool-actions.yaml').read_bytes(),
            (ROOT / 'tenant/saw/charts/governance-policy/tool-actions.yaml').read_bytes(),
        )


if __name__ == '__main__':
    unittest.main()
