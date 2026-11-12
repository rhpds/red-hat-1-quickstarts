"""Read-only synthetic sources, authenticated by the existing SAW Keycloak realm."""
import base64
import html
import json
import os
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def handler(kind, upstream, issuer):
    opener = build_opener(NoRedirect, HTTPSHandler(context=ssl.create_default_context()))

    def fetch(url, data=None, method='GET', headers=None):
        with opener.open(Request(url, data=data, method=method, headers=headers or {}), timeout=15) as response:
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                raise ValueError('source response limit')
            return body, response.headers.get('Content-Type', 'application/octet-stream')

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Request URLs, credentials and source bodies do not belong in logs.

        def reply(self, status, body, content_type='text/plain; charset=utf-8'):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            if status == 401:
                self.send_header('WWW-Authenticate', 'Basic realm="SAW lab", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(body)

        def user(self):
            auth = self.headers.get('Authorization', '')
            if not auth.startswith('Basic ') or len(auth) > 4096:
                return None
            try:
                user, password = base64.b64decode(auth[6:], validate=True).decode().split(':', 1)
            except (ValueError, UnicodeError):
                return None
            if not re.fullmatch('[a-z][a-z0-9-]{0,18}', user) or not password:
                return None
            form = urlencode({'grant_type': 'password', 'client_id': 'openshell-cli',
                              'username': user, 'password': password}).encode()
            try:
                body, _ = fetch(issuer + '/protocol/openid-connect/token', form, 'POST',
                                {'Content-Type': 'application/x-www-form-urlencoded'})
            except HTTPError as error:
                if error.code in (400, 401, 403):
                    return None
                raise
            return user if json.loads(body).get('access_token') else None

        def owns(self, message, user):
            return (str(message.get('Subject', '')).startswith(f'[SAW:{user}] ') and
                    any((r.get('Address') or r.get('Email', '')).lower() == user + '@example.test'
                        for r in message.get('To', [])))

        def email(self, path, query, user):
            if self.command != 'GET':
                return self.reply(403, 'Read-only source')
            if path in ('/', '/api/v1/messages'):
                records = []
                for start in range(0, 2000, 200):
                    data, _ = fetch(upstream + f'/api/v1/messages?start={start}&limit=200')
                    data = json.loads(data)
                    records.extend(m for m in data['messages'] if self.owns(m, user))
                    if start + len(data['messages']) >= data['total']:
                        break
                    if not data['messages']:
                        raise ValueError('incomplete mailbox pagination')
                else:
                    raise ValueError('mailbox exceeds lab limit')
                if path == '/':
                    links = ''.join(f'<li><a href="/message/{html.escape(m["ID"], quote=True)}">{html.escape(m["Subject"])}</a></li>' for m in records)
                    return self.reply(200, f'<!doctype html><title>Mailpit — {user}</title><h1>Mailpit — {user}</h1><p>Read-only lab inbox</p><ul>{links}</ul>', 'text/html; charset=utf-8')
                query = parse_qs(query)
                start = max(0, int(query.get('start', ['0'])[0]))
                limit = max(1, min(200, int(query.get('limit', ['100'])[0])))
                return self.reply(200, json.dumps({'total': len(records), 'messages': records[start:start + limit]}), 'application/json')
            match = re.fullmatch(r'/(api/v1/message|message)/([a-zA-Z0-9-]+)', path)
            if not match:
                return self.reply(403, 'Unsupported source operation')
            data, _ = fetch(upstream + '/api/v1/message/' + match[2])
            message = json.loads(data)
            if not self.owns(message, user):
                return self.reply(404, 'Message not found')
            if match[1] == 'message':
                page = f'<!doctype html><title>Mailpit</title><a href="/">Inbox</a><h1>{html.escape(message["Subject"])}</h1><pre>{html.escape(message.get("Text", ""))}</pre>'
                return self.reply(200, page, 'text/html; charset=utf-8')
            return self.reply(200, data, 'application/json')

        def calendar(self, path, query, user):
            if self.command not in ('GET', 'PROPFIND'):
                return self.reply(403, 'Read-only source')
            root = f'/{user}/{user}/'
            if path in ('/', '/.web/') and self.command == 'GET':
                data, _ = fetch(upstream + root)
                page = f'<!doctype html><title>Radicale — {user}</title><h1>Radicale — {user}</h1><p>Read-only lab calendar (UTC)</p><pre>{html.escape(data.decode())}</pre>'
                return self.reply(200, page, 'text/html; charset=utf-8')
            if (query or '%' in path or not path.startswith(root) or
                    any(part in ('.', '..') for part in path.split('/')) or '//' in path):
                return self.reply(403, 'Calendar outside assigned collection')
            size = int(self.headers.get('Content-Length', 0))
            if size < 0 or size > 8192:
                return self.reply(413, 'Request too large')
            headers = {'Depth': '1', 'Content-Type': 'application/xml'} if self.command == 'PROPFIND' else {}
            data, content_type = fetch(upstream + path, self.rfile.read(size) if size else None,
                                       self.command, headers)
            return self.reply(207 if self.command == 'PROPFIND' else 200, data, content_type)

        def handle_source(self):
            if self.path == '/healthz' and self.command == 'GET':
                return self.reply(200, 'ready')
            try:
                user = self.user()
                if not user:
                    return self.reply(401, 'Use your provisioned lab username and password')
                parsed = urlsplit(self.path)
                if parsed.scheme or parsed.netloc:
                    return self.reply(403, 'Invalid source path')
                return (self.email if kind == 'mailpit' else self.calendar)(parsed.path, parsed.query, user)
            except HTTPError as error:
                return self.reply(404 if error.code == 404 else 503, 'Source unavailable')
            except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
                return self.reply(503, 'Identity or source unavailable')

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_PROPFIND = do_MKCOL = do_MKCALENDAR = handle_source

    return Gateway


if __name__ == '__main__':
    issuer = os.environ['OIDC_ISSUER'].rstrip('/')
    if urlsplit(issuer).scheme != 'https':
        raise SystemExit('OIDC_ISSUER must use verified HTTPS')
    ThreadingHTTPServer(('0.0.0.0', 8080), handler(os.environ['SOURCE_KIND'],
                        os.environ['SOURCE_UPSTREAM'], issuer)).serve_forever()
