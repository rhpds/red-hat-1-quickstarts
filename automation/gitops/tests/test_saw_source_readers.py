import base64
import importlib.util
import json
import os
import subprocess
import sys
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
    def bundle(self):
        values = {'profiles': ['demo-assistant'], 'harnessEnabled': True,
                  'demoAssistant': {'enabled': True, 'clusterDomain': 'test.example',
                                    'demoId': 'user-test', 'tenantUser': 'user-test'}}
        output = subprocess.check_output(['helm', 'template', 'test', str(ROOT / 'tenant/saw/charts/saw-bom'),
                                          '-f', '-'], input=yaml.safe_dump(values), text=True)
        data = yaml.safe_load(output)['data']
        bundle = installer.parse_harness_files({k: base64.b64decode(v) for k, v in data.items()
                                               if k.startswith('harness__')})['demo-assistant']
        return {name: (base64.b64decode(raw), False) for name, raw in bundle.files.items()}

    def test_source_tools_and_tool_gate_behavior(self):
        result = subprocess.run(['node', '--test', '--test-isolation=none',
                                 str(ROOT / 'tests/test_saw_source_readers.mjs'),
                                 str(PATH.parent / 'tool-gate.test.mjs')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_harness_checks_all_three_governed_sources(self):
        tree = self.bundle()
        info = installer.describe_harness_tree(tree, inline=True)
        self.assertEqual(info['mcpServers'], ['demo-assistant'])
        self.assertEqual({g['governanceProfile'] for g in info['governance']},
                         {'mailpit', 'mattermost', 'calendar'})
        self.assertEqual(tree['mcp/briefing-lib.mjs'][0],
                         (ROOT / 'tenant/saw/charts/saw-bom/harness/daily-briefing/mcp/briefing-lib.mjs').read_bytes())
        applier = installer.ProfileApplier.__new__(installer.ProfileApplier)
        applier.governance_catalog = lambda ws: {p: set() for p in ['mailpit', 'mattermost', 'calendar']}
        ws = installer.Workspace(name='default')
        providers = [installer.Provider(name=p, type=p) for p in ['mailpit', 'mattermost', 'calendar']]
        applier.usable = lambda ws: providers
        sandbox = installer.Sandbox(name='notebook', providers=[p.name for p in providers])
        applier.check_harness_governance(ws, sandbox, info)
        for missing in ['mailpit', 'mattermost', 'calendar']:
            sandbox.providers = [p.name for p in providers if p.name != missing]
            with self.assertRaisesRegex(installer.InstallerError, missing):
                applier.check_harness_governance(ws, sandbox, info)
        self.assertEqual(installer.openclaw_harness_config(info)['plugins.load.paths'], ['/sandbox/harness'])

    def test_rendered_mcp_process_initializes_lists_tools_and_reports_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (content, _) in self.bundle().items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            requests = [
                {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                {'id': 2, 'method': 'tools/list'},
                {'id': 3, 'method': 'tools/call', 'params': {'name': 'saw_read_email', 'arguments': {'url': 'https://other.invalid'}}},
                {'id': 4, 'method': 'tools/call', 'params': {'name': 'saw_read_email', 'arguments': {}}},
            ]
            result = subprocess.run(['node', str(root / 'mcp/source-readers.mjs')],
                                    input='\n'.join(json.dumps(r) for r in requests) + '\n',
                                    env={'PATH': os.environ['PATH']}, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            replies = {r['id']: r for r in map(json.loads, result.stdout.splitlines())}
            self.assertEqual(replies[1]['result']['serverInfo']['name'], 'demo-assistant')
            self.assertEqual({t['name'] for t in replies[2]['result']['tools']},
                             {'saw_read_email', 'saw_read_chat', 'saw_read_calendar', 'saw_save_report', 'saw_upload_summary'})
            self.assertTrue(replies[3]['result']['isError'])
            self.assertIn('accept no arguments', replies[3]['result']['content'][0]['text'])
            self.assertTrue(replies[4]['result']['isError'])
            self.assertIn('placeholder is unavailable', replies[4]['result']['content'][0]['text'])

    def test_shared_preflight_migrates_old_plugin_and_restores_previous_tool_scope(self):
        info = installer.describe_harness_tree(self.bundle(), inline=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / '.openclaw'
            root.mkdir()
            config = root / 'openclaw.json'
            before = {'profile': 'full', 'allow': ['read']}
            old = ['saw_read_email', 'saw_read_chat', 'saw_read_calendar', 'saw_save_report', 'saw_upload_summary']
            config.write_text(json.dumps({'tools': {'profile': 'full', 'allow': old, 'toolSearch': False},
                'plugins': {'load': {'paths': [directory + '/.saw/trusted/source-readers']},
                            'entries': {'saw-source-readers': {'enabled': True}, 'saw-tool-gate': {'enabled': True}},
                            'allow': ['saw-source-readers', 'saw-tool-gate']}}))
            (root / 'saw-source-tools-before.json').write_text(json.dumps(before))
            script = installer._OPENCLAW_PREFLIGHT.replace('/sandbox', directory)
            def apply(tools):
                subprocess.run(['node', '-e', script, json.dumps({'channels': ['mattermost'], 'tools': tools})],
                               check=True, capture_output=True)
                return json.loads(config.read_text())
            for _ in range(2):
                after = apply(info['toolAllowlist'])
                self.assertEqual(after['tools']['allow'], info['toolAllowlist'])
                self.assertNotIn('saw-source-readers', after['plugins']['entries'])
                self.assertNotIn('saw-source-readers', after['plugins']['allow'])
                self.assertEqual(after['plugins']['load']['paths'], [])
                self.assertTrue(after['plugins']['entries']['saw-tool-gate']['enabled'])
                self.assertFalse(after['channels']['mattermost']['enabled'])
            self.assertEqual(apply([])['tools'], before)
            self.assertFalse((root / 'saw-source-tools-before.json').exists())
            # Disabling a harness must preserve a later operator change.
            apply(info['toolAllowlist'])
            cfg = json.loads(config.read_text())
            cfg['tools']['allow'] = ['operator-tool']
            config.write_text(json.dumps(cfg))
            self.assertEqual(apply([])['tools']['allow'], ['operator-tool'])

    def test_gate_bundle_contains_only_enforcement_assets(self):
        applier = installer.ProfileApplier.__new__(installer.ProfileApplier)
        applier.cfg = {'dashboard': {'owner': 'user-test'}, 'ownerSubject': 'subject-test'}
        tree, _, _, _ = applier.tool_gate_bundle(installer.Workspace(name='default'), installer.Sandbox(name='notebook'))
        self.assertFalse(any(p.startswith('source-readers/') for p in tree))
        self.assertIn(b'defaultAction: deny', tree['tool-actions.yaml'][0])
        self.assertEqual((PATH.parent / 'tool-actions.yaml').read_bytes(),
                         (ROOT / 'tenant/saw/charts/governance-policy/tool-actions.yaml').read_bytes())

    def test_harness_tool_scope_is_applied_after_openclaw_configuration(self):
        info = installer.describe_harness_tree(self.bundle(), inline=True)
        applier = installer.ProfileApplier.__new__(installer.ProfileApplier)
        applier.harness_info = {('default', 'notebook'): info}
        calls = []
        applier.cli = lambda *args, **kwargs: calls.append(args)
        applier.configure_harness_mcp = lambda *args: calls.append(('mcp-configured',))
        applier.configure_harness(installer.Workspace(name='default'),
                                  installer.Sandbox(name='notebook', type='openclaw'), (), 'openclaw-env')
        self.assertEqual(calls[-1][:2], ('node', '-e'))
        self.assertEqual(json.loads(calls[-1][-1])['tools'], info['toolAllowlist'])


if __name__ == '__main__':
    unittest.main()
