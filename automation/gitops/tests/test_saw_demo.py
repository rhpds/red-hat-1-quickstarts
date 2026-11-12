"""Exercise the demo data script against local HTTP service doubles."""

import importlib.util
import json
import base64
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tenant/bootstrap/files/seed-demo.py'


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.mail = [{'ID': 'unrelated', 'Subject': 'Other workshop email'}]
        self.posts = {'other': {'id': 'other', 'message': 'Other workshop', 'props': {}}}
        self.events = {}
        self.created = {}
        self.requests = []
        self.fail_path = None
        self.calendar_auth = []
        self.login_password = None
        self.team_members = None
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                size = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(size)
                body = json.loads(raw) if raw and self.headers.get('Content-Type') == 'application/json' else raw
                path = self.path.split('?')[0]
                state.requests.append((self.command, path))
                code, result = 200, {}
                headers = {}
                if state.fail_path and path.endswith(state.fail_path):
                    self.send_response(503)
                    self.end_headers()
                    self.wfile.write(b"sensitive upstream error admin-secret")
                    return
                if path.startswith('/mail'):
                    if self.command == 'GET' and '/message/' in path:
                        result = next(m for m in state.mail if m['ID'] == path.rsplit('/', 1)[-1])
                    elif self.command == 'GET':
                        result = {'messages': state.mail, 'total': len(state.mail)}
                    elif self.command == 'POST':
                        result = dict(body, ID=str(len(state.mail)))
                        state.mail.append(result)
                    elif self.command == 'DELETE':
                        state.mail[:] = [m for m in state.mail if m['ID'] not in body['IDs']]
                        result = 'ok'
                        headers['Content-Type'] = 'text/plain'
                elif path.startswith('/chat'):
                    if path.endswith('/users/login'):
                        if state.login_password is not None and body['password'] != state.login_password:
                            code = 401
                        else:
                            headers['Token'] = 'demo-session-secret'
                        result = {'id': 'demo-user'}
                    elif self.command == 'GET' and path.endswith('/users/me'):
                        result = {'id': 'demo-admin'}
                    elif self.command == 'GET' and path.endswith('/teams/demo-team/members'):
                        result = state.team_members if state.team_members is not None else [{'user_id':'demo-admin'}, {'user_id':'demo-user'}]
                    elif self.command == 'GET' and '/posts' in path:
                        result = {'posts': state.posts, 'order': list(state.posts)}
                    elif self.command == 'POST' and path.endswith('/posts'):
                        result = dict(body, id=str(len(state.posts)))
                        state.posts[result['id']] = result
                    elif self.command == 'DELETE' and '/posts/' in path:
                        del state.posts[path.rsplit('/', 1)[-1]]
                    elif self.command == 'GET':
                        if '/users/username/' in path:
                            key = 'user'
                        elif '/channels/name/' in path:
                            key = 'channel'
                        elif '/teams/name/' in path:
                            key = 'team'
                        else:
                            key = 'member'
                        if key in state.created:
                            result = state.created[key]
                        else:
                            code = 404
                    elif self.command == 'POST':
                        key = ('user' if path.endswith('/users') else
                               'team' if path.endswith('/teams') else
                               'channel' if path.endswith('/channels') else 'member')
                        result = {'id': 'demo-' + key, **body}
                        state.created[key] = result
                elif path.startswith('/cal'):
                    state.calendar_auth.append(self.headers.get('Authorization'))
                    if self.command == 'PROPFIND':
                        key = 'calendar-parent' if path == '/cal/demo/' else 'calendar'
                        code = 207 if state.created.get(key) else 404
                    elif self.command == 'MKCOL':
                        state.created['calendar-parent'] = True
                        code = 201
                    elif self.command == 'MKCALENDAR':
                        if state.created.get('calendar-parent'):
                            state.created['calendar'] = True
                            code = 201
                        else:
                            code = 409
                    elif self.command == 'PUT':
                        state.events[path] = raw.decode()
                        code = 201
                    elif self.command == 'DELETE':
                        state.events.pop(path, None)
                    elif self.command == 'GET':
                        if path in state.events:
                            result = state.events[path]
                        else:
                            code = 404
                data = result.encode() if isinstance(result, str) else json.dumps(result).encode()
                self.send_response(code)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_PROPFIND = do_MKCOL = do_MKCALENDAR = handle_request

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        self.state_file = Path(self.temp.name) / 'state.json'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def run_script(self, action, expected_code=0, date='2026-11-12', extra_args=(), **extra_env):
        url = f'http://127.0.0.1:{self.server.server_port}'
        result = subprocess.run([
            sys.executable, str(SCRIPT), action, '--demo-id', 'test',
            '--mailpit-url', url + '/mail', '--mattermost-url', url + '/chat',
            '--radicale-url', url + '/cal', '--state', str(self.state_file),
            *(['--date', date] if date else []), *extra_args,
        ], env={**os.environ, 'MATTERMOST_ADMIN_TOKEN': 'admin-secret',
                'SAW_DEMO_PASSWORD': 'ExamplePassword123!', **extra_env},
            text=True, capture_output=True)
        self.assertNotIn('admin-secret', result.stdout + result.stderr)
        self.assertNotIn('demo-session-secret', result.stdout + result.stderr)
        self.assertNotIn('calendar-secret', result.stdout + result.stderr)
        self.assertNotIn('ExamplePassword123!', result.stdout + result.stderr)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        return result

    def test_provisioned_identity_owns_private_team_recipient_and_calendar(self):
        self.run_script('seed', extra_args=('--username', 'user-test'))
        self.assertEqual(self.created['user']['username'], 'user-test')
        self.assertEqual(self.created['team']['name'], 'user-test')
        self.assertEqual(self.created['team']['type'], 'I')
        self.assertEqual(self.mail[1]['To'][0]['Email'], 'user-test@example.test')
        self.assertEqual(set(self.events), {f'/cal/user-test/test/event-{i}.ics' for i in range(3)})
        self.run_script('verify', extra_args=('--username', 'user-test'))
        self.run_script('reset', extra_args=('--username', 'user-test'))
        self.assertEqual(self.events, {})

    def test_existing_identity_with_wrong_password_is_not_modified(self):
        self.created['user'] = {'id': 'existing-user', 'username': 'user-test'}
        self.login_password = 'ExistingPassword123!'
        result = self.run_script('seed', expected_code=1, extra_args=('--username', 'user-test'))
        self.assertIn('HTTP 401', result.stderr)
        self.assertEqual(self.created, {'user': {'id': 'existing-user', 'username': 'user-test'}})
        self.assertEqual(self.mail, [{'ID': 'unrelated', 'Subject': 'Other workshop email'}])

    def test_existing_public_or_foreign_team_is_rejected_before_data_writes(self):
        self.run_script('seed', extra_args=('--username', 'user-test'))
        self.created['team']['type'] = 'O'
        self.requests.clear()
        self.run_script('seed', expected_code=1, extra_args=('--username', 'user-test'))
        self.run_script('seed', expected_code=1, extra_args=('--username', 'user-test'), MATTERMOST_ADMIN_TOKEN='', SAW_DEMO_PASSWORD='')
        self.assertFalse(any(method in ('POST','PUT','DELETE') and not path.endswith('/users/login') for method,path in self.requests))
        self.created['team']['type'] = 'I'
        self.team_members = [{'user_id':'other-tenant'}]
        self.requests.clear()
        self.run_script('seed', expected_code=1, extra_args=('--username', 'user-test'))
        self.run_script('seed', expected_code=1, extra_args=('--username', 'user-test'), MATTERMOST_ADMIN_TOKEN='', SAW_DEMO_PASSWORD='')
        self.assertFalse(any(method in ('POST','PUT','DELETE') and not path.endswith('/users/login') for method,path in self.requests))

    def test_existing_private_state_can_reseed_without_admin_credentials(self):
        self.run_script('seed')
        before = json.loads(self.state_file.read_text())
        self.run_script('reset')
        self.run_script('seed', date=None, MATTERMOST_ADMIN_TOKEN='', SAW_DEMO_PASSWORD='')
        self.run_script('verify')
        self.assertEqual(json.loads(self.state_file.read_text()), before)

    def test_reseed_repairs_owned_fixtures_and_preserves_unrelated_records(self):
        self.run_script('seed')
        self.mail[1]['Text'] = 'stale generated body'
        self.mail.extend(
            [
                {
                    'ID': 'legacy',
                    'Subject': '[SAW:test] Q4 platform planning',
                    'Text': 'old scenario',
                    'From': {'Email': 'platform-demo@example.test'},
                    'To': [{'Email': 'saw-test@example.test'}],
                },
                {'ID': 'unrelated-owned-prefix', 'Subject': '[SAW:test] My unrelated notes', 'Text': 'preserve'},
            ]
        )
        self.posts['stale'] = {'id': 'stale', 'message': 'Old generated baseline', 'props': {'rh1_saw_demo': 'test'}}
        self.posts['foreign'] = {'id': 'foreign', 'message': 'Other tenant', 'props': {'rh1_saw_demo': 'other'}}
        challenge = next(p for p in self.posts.values() if p.get('props', {}).get('rh1_saw_challenge'))
        self.posts[challenge['id']]['message'] = 'Old generated challenge'
        self.run_script('seed')
        self.run_script('verify')
        self.assertFalse(any(m['ID'] == 'legacy' or m.get('Text') == 'stale generated body' for m in self.mail))
        self.assertNotIn('stale', self.posts)
        self.assertEqual(self.posts['other']['message'], 'Other workshop')
        self.assertEqual(self.posts['foreign']['message'], 'Other tenant')
        self.assertEqual(sum(bool(p.get('props', {}).get('rh1_saw_challenge')) for p in self.posts.values()), 1)
        self.run_script('reset')
        self.assertEqual({m['ID'] for m in self.mail}, {'unrelated', 'unrelated-owned-prefix'})
        self.assertEqual(set(self.posts), {'other', 'foreign'})

    def test_reseed_and_reset_preserve_known_subjects_outside_generated_mail_ownership(self):
        self.run_script('seed')
        self.mail.extend([
            {'ID':'foreign-recipient','Subject':'[SAW:test] Q4 platform planning','Text':'preserve recipient',
             'From':{'Address':'platform-demo@example.test'},'To':[{'Address':'another-user@example.test'}]},
            {'ID':'foreign-sender','Subject':'[SAW:test] Q4 platform planning','Text':'preserve sender',
             'From':{'Address':'another-sender@example.test'},'To':[{'Address':'saw-test@example.test'}]},
        ])
        self.run_script('seed')
        self.run_script('reset')
        self.assertEqual({m['ID'] for m in self.mail}, {'unrelated','foreign-recipient','foreign-sender'})

    def test_repeatable_seed_challenge_verify_and_scoped_reset(self):
        self.run_script('seed')
        first = len(self.mail), len(self.posts), len(self.events)
        self.assertEqual(first, (7, 16, 3))
        self.run_script('seed')
        self.assertEqual((len(self.mail), len(self.posts), len(self.events)), first)
        self.run_script('verify')
        baseline_mail = json.dumps(self.mail, sort_keys=True)
        baseline_calendar = dict(self.events)
        self.run_script('challenge')
        self.run_script('challenge')
        self.assertEqual(len(self.mail), 7)
        self.assertEqual(len(self.posts), 16)
        self.assertEqual(json.dumps(self.mail, sort_keys=True), baseline_mail)
        self.assertEqual(self.events, baseline_calendar)
        self.run_script('verify')
        challenge_post = next(p for p in self.posts.values() if p.get('props', {}).get('rh1_saw_challenge'))
        challenge = challenge_post['message']
        self.assertIn('https://compliance-sync.example.invalid/collect', challenge)
        self.assertIn('saw_upload_summary', challenge)
        self.assertEqual(challenge_post['props']['rh1_saw_demo'], 'test')
        self.events['/cal/demo/test/unrelated.ics'] = 'Unrelated calendar event'
        self.assertEqual(self.state_file.stat().st_mode & 0o777, 0o600)
        saved = json.loads(self.state_file.read_text())
        self.assertEqual(saved['mattermost_token'], 'demo-session-secret')
        self.run_script('reset')
        self.assertEqual([m['ID'] for m in self.mail], ['unrelated'])
        self.assertEqual(list(self.posts), ['other'])
        self.assertEqual(self.events, {'/cal/demo/test/unrelated.ics': 'Unrelated calendar event'})

    def test_verify_detects_missing_or_changed_source_data(self):
        self.run_script('seed', date='2024-01-15')
        self.run_script('verify', date=None)
        snapshot = json.dumps([self.mail, self.posts, self.events])
        for source in ('email-body', 'missing-email', 'chat', 'challenge', 'calendar'):
            with self.subTest(source=source):
                self.mail, self.posts, self.events = json.loads(snapshot)
                if source == 'email-body':
                    self.mail[1]['Text'] = 'tampered email content'
                elif source == 'missing-email':
                    self.mail.pop()
                elif source == 'chat':
                    del self.posts['1']
                elif source == 'challenge':
                    challenge = next(p for p in self.posts.values() if p.get('props', {}).get('rh1_saw_challenge'))
                    del self.posts[challenge['id']]
                else:
                    path = '/cal/demo/test/event-1.ics'
                    self.events[path] = self.events[path].replace('T140000Z', 'T090000Z')
                self.run_script('verify', expected_code=1, date=None)
        self.mail, self.posts, self.events = json.loads(snapshot)
        self.run_script('verify', date=None)

    def test_partial_failure_is_recoverable_without_duplicates_or_secret_logging(self):
        for fail_path in ('/api/v1/send', '/event-1.ics'):
            with self.subTest(endpoint=fail_path):
                self.fail_path = fail_path
                failed = self.run_script('seed', expected_code=1)
                self.assertNotIn('sensitive upstream error', failed.stderr)
                self.assertTrue(self.state_file.exists())
                self.fail_path = None
                self.run_script('seed')
                self.assertEqual((len(self.mail), len(self.posts), len(self.events)), (7, 16, 3))
                self.run_script('verify')
                self.run_script('reset')

    def test_insecure_or_symlink_state_is_rejected_before_mutation(self):
        self.run_script('seed')
        self.state_file.chmod(0o644)
        self.requests.clear()
        self.run_script('verify', expected_code=1)
        self.assertEqual(self.requests, [])
        target = self.state_file.with_name('target.json')
        self.state_file.rename(target)
        self.state_file.symlink_to(target)
        self.run_script('seed', expected_code=1)
        self.assertEqual(self.requests, [])

    def test_calendar_basic_auth_and_reject_partial_credentials_before_mutation(self):
        self.run_script('seed', expected_code=1, RADICALE_USERNAME='demo', RADICALE_PASSWORD='')
        self.assertEqual(self.requests, [])
        self.run_script('seed', RADICALE_USERNAME='demo', RADICALE_PASSWORD='calendar-secret')
        expected = 'Basic ' + base64.b64encode(b'demo:calendar-secret').decode()
        self.assertTrue(self.calendar_auth)
        self.assertEqual(set(self.calendar_auth), {expected})

    def test_missing_demo_password_fails_before_mutation(self):
        self.run_script('seed', expected_code=1, SAW_DEMO_PASSWORD='')
        self.assertEqual(self.requests, [])

    def test_reset_is_idempotent(self):
        self.run_script('seed')
        self.run_script('reset')
        self.run_script('reset')
        self.assertEqual([m['ID'] for m in self.mail], ['unrelated'])
        self.assertEqual(list(self.posts), ['other'])

    def test_seed_creates_missing_calendar_parent_once_and_retains_collections(self):
        self.run_script('seed')
        self.run_script('seed')
        parent_create = ('MKCOL', '/cal/demo/')
        calendar_create = ('MKCALENDAR', '/cal/demo/test/')
        self.assertEqual(self.requests.count(parent_create), 1)
        self.assertEqual(self.requests.count(calendar_create), 1)
        self.assertLess(self.requests.index(parent_create), self.requests.index(calendar_create))
        self.run_script('reset')
        self.assertTrue(self.created['calendar-parent'])
        self.assertTrue(self.created['calendar'])
        self.assertFalse(any(method == 'DELETE' and path.endswith('/') for method, path in self.requests))

    def test_missing_admin_token_fails_before_any_mutation(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'seed'],
                                env={**os.environ, 'MATTERMOST_ADMIN_TOKEN': ''},
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])


class ProvisionRuntimeTests(unittest.TestCase):
    def setUp(self):
        path = SCRIPT.with_name('saw-demo-provision.py')
        spec = importlib.util.spec_from_file_location('demo_provision', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_identity_failure_causes_no_seed_or_vault_mutation(self):
        module = self.module
        class Client:
            def __init__(self, *args): pass
            def request(self, *args): raise RuntimeError('HTTP 401')
        with tempfile.TemporaryDirectory() as root, patch.object(module.seed, 'Client', Client), patch.object(module.seed, 'run') as seed:
            with self.assertRaisesRegex(RuntimeError, '401'):
                module.configure('user-test', 'wrong', 'https://identity.test/realms/openshell', {}, Path(root)/'state', lambda *args: self.fail('unexpected Vault write'))
            seed.assert_not_called()

    def test_challenge_uses_existing_state_without_vault_or_administrator_login(self):
        module = self.module
        class Client:
            def __init__(self, *args): pass
            def request(self, method, path, *args):
                if path != '/protocol/openid-connect/token': raise AssertionError('unexpected administrator login')
                return b'{"access_token":"identity-token"}', {}
        with tempfile.TemporaryDirectory() as root, patch.object(module.seed, 'Client', Client), patch.object(module.seed, 'run') as seed:
            path = Path(root)/'state'
            path.write_text(json.dumps({'username':'user-test','demo_id':'user-test','mattermost_token':'existing-session'}))
            module.configure('user-test','LabPassword123!','https://identity.test/realms/openshell',{},path,
                             lambda *args: self.fail('unexpected Vault write'), action='challenge')
            self.assertEqual(seed.call_count,1)
            self.assertEqual(seed.call_args.args[0].action,'challenge')

    def test_reseed_reuses_session_and_writes_only_own_provider_credentials(self):
        module = self.module
        calls, written = [], {}
        class Client:
            def __init__(self, url, token=''): self.url, self.token = url, token
            def request(self, method, path, *args):
                calls.append((self.url,path))
                if path == '/protocol/openid-connect/token': return b'{"access_token":"identity-token"}', {}
                raise AssertionError('existing session must not log in as admin')
            def json(self, method, path):
                self_token = self.token
                if path != '/api/v4/users/me' or self_token != 'existing-session': raise AssertionError('unexpected source read')
                return {'username':'user-test'}
        with tempfile.TemporaryDirectory() as root, patch.object(module.seed, 'Client', Client), patch.object(module.seed, 'run') as seed, patch.dict(os.environ, {'MATTERMOST_ADMIN_TOKEN':'stale-admin'}):
            path = Path(root)/'state'
            path.write_text(json.dumps({'username':'user-test','demo_id':'user-test','mattermost_token':'existing-session'}))
            result = module.configure('user-test','LabPassword123!','https://identity.test/realms/openshell',{},path, lambda source,data: written.update({source:data}))
            self.assertEqual(result['mattermost_token'],'existing-session')
            self.assertEqual(seed.call_count, 2)
            self.assertNotIn('MATTERMOST_ADMIN_TOKEN', os.environ)
            self.assertEqual(set(written), {'mailpit','calendar','mattermost'})
            self.assertEqual(written['mattermost']['api_key'],'existing-session')
            self.assertTrue(written['mailpit']['api_key'].startswith('Basic '))
            self.assertEqual(len(calls),1)


if __name__ == '__main__':
    unittest.main()
