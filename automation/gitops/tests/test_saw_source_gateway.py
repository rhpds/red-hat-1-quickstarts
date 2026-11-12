"""Exercise the shared read gateway against real localhost identity/source doubles."""

import base64
import importlib.util
import json
import os
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'infra/bootstrap/files/source-gateway.py'


class GatewayTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('source_gateway', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.calls = []
        owner = self

        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                valid = form.get('password') == ['LabPassword123!']
                self.send_response(200 if valid else 401)
                self.end_headers()
                self.wfile.write(json.dumps({'access_token': 'private-identity-token'} if valid else {}).encode())

            def do_GET(self):
                owner.calls.append((self.command, self.path, self.headers.get('Authorization')))
                records = [
                    {
                        "ID": u,
                        "Subject": f"[SAW:{u}] Planning",
                        "To": [{"Address": f"{u}@example.test"}],
                        "Text": "<script>alert(1)</script>",
                    }
                    for u in ['user-a', 'user-b']
                ]
                if self.path.startswith('/api/v1/messages'):
                    data = {'messages': records, 'total': 2}
                elif self.path.startswith('/api/v1/message/'):
                    data = next(r for r in records if r['ID'] == self.path.rsplit('/', 1)[-1])
                else:
                    data = 'BEGIN:VCALENDAR\r\nEND:VCALENDAR'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json' if isinstance(data, dict) else 'text/calendar')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode() if isinstance(data, dict) else data.encode())

            do_PROPFIND = do_GET

        self.backend = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        upstream = f'http://127.0.0.1:{self.backend.server_port}'
        self.gateway = ThreadingHTTPServer(
            ('127.0.0.1', 0), module.handler('mailpit', upstream, upstream + '/realms/openshell')
        )
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in [self.backend, self.gateway]]
        for t in self.threads:
            t.start()
        self.module, self.upstream = module, upstream

    def tearDown(self):
        if hasattr(self, 'gateway'):
            for s in [self.gateway, self.backend]: s.shutdown(); s.server_close()
            for t in self.threads: t.join()

    def request(self, path, user='user-a', password='LabPassword123!', method='GET'):
        headers = {} if user is None else {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}
        try:
            with urlopen(Request(f'http://127.0.0.1:{self.gateway.server_port}' + path, headers=headers, method=method)) as r:
                return r.status, r.read()
        except HTTPError as e:
            return e.code, e.read()

    def test_login_is_required_and_wrong_password_never_reads_backend(self):
        self.assertEqual(self.request('/api/v1/messages', user=None)[0], 401)
        self.assertEqual(self.request('/api/v1/messages', password='wrong')[0], 401)
        self.assertEqual(self.calls, [])

    def test_gateway_and_provisioner_trust_the_private_ingress_ca(self):
        with tempfile.TemporaryDirectory() as directory:
            cert, key = Path(directory) / 'ca.pem', Path(directory) / 'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1',
                            '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            identity = ThreadingHTTPServer(('127.0.0.1', 0), self.backend.RequestHandlerClass)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            identity.socket = context.wrap_socket(identity.socket, server_side=True)
            thread = threading.Thread(target=identity.serve_forever, daemon=True)
            thread.start()
            issuer = f'https://127.0.0.1:{identity.server_port}'
            try:
                with patch.dict(os.environ, {'SAW_INGRESS_CA': str(cert)}):
                    self.gateway.RequestHandlerClass = self.module.handler('mailpit', self.upstream, issuer)
                    self.assertEqual(self.request('/api/v1/messages')[0], 200)
                    seed_path = PATH.parents[3] / 'tenant/bootstrap/files/seed-demo.py'
                    spec = importlib.util.spec_from_file_location('seed_ingress_ca', seed_path)
                    seed = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(seed)
                    body, _ = seed.Client(issuer).request('POST', '/token',
                        'password=LabPassword123%21', 'application/x-www-form-urlencoded')
                    self.assertIn('access_token', json.loads(body))
            finally:
                identity.shutdown()
                identity.server_close()
                thread.join()

    def test_email_list_and_bodies_are_scoped_to_authenticated_identity(self):
        code, body = self.request('/api/v1/messages?limit=100')
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data['total'], 1)
        self.assertEqual([m['ID'] for m in data['messages']], ['user-a'])
        self.assertEqual(self.request('/api/v1/message/user-b')[0], 404)
        self.assertEqual(self.request('/api/v1/message/user-a')[0], 200)
        self.assertTrue(all(auth is None for _, _, auth in self.calls))
        self.assertNotIn(b'LabPassword', body)
        self.assertNotIn(b'private-identity-token', body)

    def test_mutations_and_unscoped_apis_are_denied(self):
        for method, path in [('DELETE','/api/v1/messages'), ('POST','/api/v1/send'), ('GET','/api/v1/search?query=*'), ('GET','/api/v1/stats')]:
            self.assertEqual(self.request(path, method=method)[0], 403)
        self.assertEqual(self.calls, [])

    def test_email_browser_view_escapes_untrusted_source_html(self):
        code, body = self.request('/message/user-a')
        self.assertEqual(code, 200)
        self.assertNotIn(b'<script>', body)
        self.assertIn(b'&lt;script&gt;', body)

    def test_calendar_only_allows_own_collection_and_read_methods(self):
        self.gateway.RequestHandlerClass = self.module.handler('calendar', self.upstream, self.upstream + '/realms/openshell')
        self.assertEqual(self.request('/user-a/user-a/')[0], 200)
        for path in ['/user-b/user-b/', '/user-a/../user-b/', '/user-a/%2e%2e/user-b/', '/user-a/%252e%252e/user-b/', '//user-b/', '/user-a/']:
            self.assertEqual(self.request(path)[0], 403, path)
        self.assertEqual(self.request('/user-a/user-a/', method='DELETE')[0], 403)
        self.assertEqual(self.request('/user-a/user-a/', method='PROPFIND')[0], 207)
        self.assertEqual(len(self.calls), 2)
