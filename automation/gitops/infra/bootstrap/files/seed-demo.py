#!/usr/bin/env python3
"""Populate only SAW demo-owned email, chat, and calendar data (stdlib only)."""
import argparse
import base64
import datetime as dt
import json
import os
import re
import secrets
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LEGACY_EMAIL_SUBJECTS = {'Q4 platform planning', 'GTC Berlin rehearsal', 'Security review', 'AI Platform actions'}
DEMO_DATA = json.loads(Path(__file__).with_name('demo-data.json').read_text())
CHALLENGE_MESSAGE = DEMO_DATA['challenge']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an administrator credential to a redirected endpoint.
        return None


class Client:
    def __init__(self, url, token='', username='', password=''):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise ValueError('service URL must be HTTP(S) without embedded credentials')
        if parsed.query or parsed.fragment:
            raise ValueError('service URL must not contain a query or fragment')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1') and not parsed.hostname.endswith('.svc.cluster.local'):
            raise ValueError('use HTTPS for remote services or a local port-forward')
        if bool(username) != bool(password):
            raise ValueError('set both RADICALE_USERNAME and RADICALE_PASSWORD, or neither for a local no-auth service')
        self.url, self.token = url.rstrip('/'), token
        self.basic_auth = ('Basic ' + base64.b64encode((username + ':' + password).encode()).decode()) if username else ''
        context = ssl.create_default_context()
        if os.environ.get('SAW_INGRESS_CA'):
            context.load_verify_locations(cafile=os.environ['SAW_INGRESS_CA'])
        self.opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context))

    def request(self, method, path, body=None, content_type=None, missing=False):
        headers = {}
        if self.basic_auth:
            headers['Authorization'] = self.basic_auth
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            content_type = 'application/json'
        elif isinstance(body, str):
            body = body.encode()
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.url + path, body, headers, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None, {}
            raise RuntimeError(f'{method} {path.split("?")[0]} failed with HTTP {error.code}') from None
        except urllib.error.URLError:
            raise RuntimeError('service connection failed; verify endpoint, readiness and TLS trust') from None

    def json(self, method, path, body=None, missing=False):
        data, _ = self.request(method, path, body, missing=missing)
        return None if data is None else json.loads(data or '{}')


def messages(mail):
    result, start = [], 0
    while True:
        page = mail.json('GET', f'/api/v1/messages?start={start}&limit=200')
        batch = page['messages']
        result.extend(batch)
        start += len(batch)
        if not batch or start >= page['total']:
            return result


def posts(chat, channel):
    result, page = [], 0
    while True:
        batch = chat.json('GET', f'/api/v4/channels/{channel}/posts?page={page}&per_page=200')['posts']
        result.extend(batch.values())
        if len(batch) < 200:
            return result
        page += 1


def fixtures(day):
    # Resolve scenario weekdays relative to the persisted seed date.
    dates = {'today': day}
    for weekday, name in ((0, 'monday'), (1, 'tuesday'), (2, 'wednesday'), (4, 'friday')):
        dates[name] = day + dt.timedelta(days=(weekday - day.weekday()) % 7 or 7)
    labels = {name: date.isoformat() for name, date in dates.items()}
    emails = [(mail['subject'], mail['body'].format_map(labels)) for mail in DEMO_DATA['emails']]
    events = []
    for number, event in enumerate(DEMO_DATA['calendar']):
        date, hour = dates[event['day']], event['hour']
        start = date.strftime('%Y%m%d') + f'T{hour:02d}0000Z'
        end = date.strftime('%Y%m%d') + f'T{hour + 1:02d}0000Z'
        events.append((number, event['summary'], start, end))
    return emails, DEMO_DATA['chat'], events


def seed_challenge(chat, demo_id, channel_id, owned_posts):
    found = False
    for post in owned_posts:
        if not post.get('props', {}).get('rh1_saw_challenge'):
            continue
        if post['message'] == CHALLENGE_MESSAGE and not found:
            found = True
        else:
            chat.json('DELETE', '/api/v4/posts/' + post['id'])
    if not found:
        chat.json('POST', '/api/v4/posts', {
            'channel_id': channel_id, 'message': CHALLENGE_MESSAGE,
            'props': {'rh1_saw_demo': demo_id, 'rh1_saw_challenge': True},
        })


def prepare_chat(admin, args):
    username = 'saw-' + args.demo_id
    password = os.environ.get('SAW_DEMO_PASSWORD', '')
    if not password:
        raise ValueError('set SAW_DEMO_PASSWORD for the dedicated demo user')
    user = admin.json('GET', '/api/v4/users/username/' + username, missing=True)
    if user is None:
        user = admin.json('POST', '/api/v4/users', {
            'username': username, 'email': username + '@example.test', 'password': password,
        })
    _, headers = admin.request('POST', '/api/v4/users/login', {'login_id': username, 'password': password})
    token = headers.get('Token')
    if not token:
        raise RuntimeError('Mattermost login did not return a session token')
    team = admin.json('GET', '/api/v4/teams/name/' + username, missing=True)
    if team is None:
        team = admin.json('POST', '/api/v4/teams', {'name': username, 'display_name': 'SAW ' + args.demo_id, 'type': 'O'})
    member_path = f'/api/v4/teams/{team["id"]}/members/{user["id"]}'
    if admin.json('GET', member_path, missing=True) is None:
        admin.json('POST', f'/api/v4/teams/{team["id"]}/members', {'team_id': team['id'], 'user_id': user['id']})
    channel = admin.json('GET', f'/api/v4/teams/{team["id"]}/channels/name/ai-platform', missing=True)
    if channel is None:
        channel = admin.json('POST', '/api/v4/channels', {'team_id': team['id'], 'name': 'ai-platform', 'display_name': 'AI Platform', 'type': 'O'})
    member_path = f'/api/v4/channels/{channel["id"]}/members/{user["id"]}'
    if admin.json('GET', member_path, missing=True) is None:
        admin.json('POST', f'/api/v4/channels/{channel["id"]}/members', {'user_id': user['id']})
    return {'demo_id': args.demo_id, 'channel_id': channel['id'], 'username': username,
            'mattermost_token': token, 'mailpit_url': args.mailpit_url,
            'mattermost_url': args.mattermost_url, 'radicale_url': args.radicale_url}


def save_state(path, state):
    # Only this file contains the non-admin demo session; never print it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(state, output, indent=2)


def run(args):
    if args.state.is_symlink():
        raise ValueError('state file must not be a symbolic link')
    if args.state.exists() and args.state.stat().st_mode & 0o077:
        raise ValueError('state file must be private; restrict its permissions to 0600')
    mail = Client(args.mailpit_url)
    calendar = Client(args.radicale_url, username=os.environ.get('RADICALE_USERNAME', ''),
                      password=os.environ.get('RADICALE_PASSWORD', ''))
    if args.action == 'seed' and (not args.state.exists() or os.environ.get('MATTERMOST_ADMIN_TOKEN')):
        token = os.environ.get('MATTERMOST_ADMIN_TOKEN', '')
        if not token:
            raise ValueError('set MATTERMOST_ADMIN_TOKEN for initial population')
        args.date = args.date or dt.datetime.now(dt.timezone.utc).date()
        state = prepare_chat(Client(args.mattermost_url, token), args)
        state['date'] = args.date.isoformat()
        save_state(args.state, state)
    else:
        state = json.loads(args.state.read_text())
        args.date = args.date or dt.date.fromisoformat(state['date'])
        for key in ('demo_id', 'mailpit_url', 'mattermost_url', 'radicale_url'):
            if state[key] != getattr(args, key):
                raise ValueError('state does not match the selected demo and endpoints; use its original configuration')
        if args.action == 'seed' and state['date'] != args.date.isoformat():
            state['date'] = args.date.isoformat()
            save_state(args.state, state)
    chat = Client(args.mattermost_url, state['mattermost_token'])
    prefix = f'[SAW:{args.demo_id}] '
    owner = 'demo'
    collection = '/' + owner + '/' + args.demo_id + '/'
    emails, chat_text, events = fixtures(args.date)
    owned_subjects = {prefix + subject for subject, _ in emails}
    legacy_subjects = {prefix + subject for subject in LEGACY_EMAIL_SUBJECTS}
    recipient = state['username'].lower() + '@example.test'
    owned_mail = [m for m in messages(mail)
                  if m['Subject'] in owned_subjects | legacy_subjects
                  and (m.get('From', {}).get('Address') or m.get('From', {}).get('Email', '')).lower() == 'platform-demo@example.test'
                  and any((r.get('Address') or r.get('Email', '')).lower() == recipient for r in m.get('To', []))]
    owned_posts = [p for p in posts(chat, state['channel_id']) if p.get('props', {}).get('rh1_saw_demo') == args.demo_id]

    if args.action == 'reset':
        if owned_mail:
            mail.request('DELETE', '/api/v1/messages', {'IDs': [m['ID'] for m in owned_mail]})
        for post in owned_posts:
            chat.json('DELETE', '/api/v4/posts/' + post['id'])
        for number, *_ in events:
            calendar.request('DELETE', collection + f'event-{number}.ics', missing=True)
        print('Removed only this demo\'s messages and calendar items; user and channel retained.')
        return

    if args.action == 'verify':
        expected = {prefix + subject for subject, _ in emails}
        if not expected.issubset({m['Subject'] for m in owned_mail}):
            raise RuntimeError('baseline emails are missing; rerun seed')
        for subject, expected_text in emails:
            matching = [m for m in owned_mail if m['Subject'] == prefix + subject]
            if not any(mail.json('GET', '/api/v1/message/' + m['ID']).get('Text') == expected_text for m in matching):
                raise RuntimeError('baseline email content does not match the demo; reset and reseed')
        if not set(chat_text).issubset({p['message'] for p in owned_posts}):
            raise RuntimeError('baseline chat messages are missing; rerun seed')
        if not any(p.get('props', {}).get('rh1_saw_challenge') and p['message'] == CHALLENGE_MESSAGE for p in owned_posts):
            raise RuntimeError('prepared challenge message is missing; rerun seed')
        for number, summary, start, end in events:
            data, _ = calendar.request('GET', collection + f'event-{number}.ics')
            content = data.decode()
            if not all(value in content.splitlines() for value in (
                    'SUMMARY:' + summary, 'DTSTART:' + start, 'DTEND:' + end)):
                raise RuntimeError('calendar content does not match the demo')
        print('Verified baseline email, chat and calendar data. Agent execution and enforcement are separate live checks.')
        return

    if args.action == 'challenge':
        seed_challenge(chat, args.demo_id, state['channel_id'], owned_posts)
        print(f'challenge complete for {args.demo_id}; untrusted training post is in ai-platform.')
        return
    expected_text = {prefix + subject: text for subject, text in emails}
    stale_mail = [m for m in owned_mail if m['Subject'] not in expected_text or
                  mail.json('GET', '/api/v1/message/' + m['ID']).get('Text') != expected_text[m['Subject']]]
    if stale_mail:
        mail.request('DELETE', '/api/v1/messages', {'IDs': [m['ID'] for m in stale_mail]})
        stale_ids = {m['ID'] for m in stale_mail}
        owned_mail = [m for m in owned_mail if m['ID'] not in stale_ids]
    subjects = {m['Subject'] for m in owned_mail}
    for subject, text in emails:
        if prefix + subject not in subjects:
            mail.json('POST', '/api/v1/send', {
                'From': {'Email': 'platform-demo@example.test', 'Name': 'SAW training'},
                'To': [{'Email': state['username'] + '@example.test'}],
                'Subject': prefix + subject, 'Text': text,
            })
    if args.action == 'seed':
        # Replace only this demo's obsolete generated baseline, retaining
        # the challenge, untagged conversation and other tenants' posts.
        for post in owned_posts:
            if not post.get('props', {}).get('rh1_saw_challenge') and post['message'] not in chat_text:
                chat.json('DELETE', '/api/v4/posts/' + post['id'])
        for text in chat_text:
            if text not in {p['message'] for p in owned_posts}:
                chat.json('POST', '/api/v4/posts', {'channel_id': state['channel_id'], 'message': text,
                          'props': {'rh1_saw_demo': args.demo_id}})
        seed_challenge(chat, args.demo_id, state['channel_id'], owned_posts)
        data, _ = calendar.request('PROPFIND', '/' + owner + '/', missing=True)
        if data is None:
            calendar.request('MKCOL', '/' + owner + '/')
        data, _ = calendar.request('PROPFIND', collection, missing=True)
        if data is None:
            calendar.request('MKCALENDAR', collection,
                '<c:mkcalendar xmlns:c="urn:ietf:params:xml:ns:caldav"><d:set xmlns:d="DAV:"><d:prop><d:displayname>SAW demo</d:displayname></d:prop></d:set></c:mkcalendar>', 'application/xml')
        for number, summary, start, end in events:
            content = '\r\n'.join([
                'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//RH One SAW demo//EN',
                'BEGIN:VEVENT', f'UID:saw-{args.demo_id}-{number}@example.test',
                'DTSTAMP:' + args.date.strftime('%Y%m%d') + 'T000000Z',
                'DTSTART:' + start, 'DTEND:' + end, 'SUMMARY:' + summary,
                'END:VEVENT', 'END:VCALENDAR', '',
            ])
            calendar.request('PUT', collection + f'event-{number}.ics', content, 'text/calendar; charset=utf-8')
    print(f'{args.action} complete for {args.demo_id}; private connection details saved in the state file.')


def kube_state(body=None, legacy=False):
    root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    location = 'openshell-agents/secrets/saw-demo-admin' if legacy else 'vault/secrets/saw-demo-state'
    request = urllib.request.Request('https://kubernetes.default.svc/api/v1/namespaces/' + location,
        data=json.dumps(body).encode() if body else None,
        headers={'Authorization': 'Bearer ' + (root / 'token').read_text().strip(),
                 'Content-Type': 'application/merge-patch+json'}, method='PATCH' if body else 'GET')
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(
        context=ssl.create_default_context(cafile=str(root / 'ca.crt'))))
    try:
        with opener.open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if legacy and error.code == 404:
            return {}
        raise


def publish_chat(token):
    request = urllib.request.Request('https://vault.vault.svc:8200/v1/secret/data/hub/saw-demo/mattermost',
        data=json.dumps({'data': {'provider': 'mattermost', 'api_key': token}}).encode(), method='POST',
        headers={'X-Vault-Token': Path('/vault-token/token').read_text().strip(), 'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(
        context=ssl.create_default_context(cafile='/ca/service-ca.crt')))
    with opener.open(request, timeout=30):
        pass


def setup_shared(args):
    args.demo_id = 'rh1'
    args.mailpit_url = 'http://mailpit.openshell-agents.svc.cluster.local:8025'
    args.mattermost_url = 'http://mattermost.openshell-agents.svc.cluster.local:8065'
    args.radicale_url = 'http://radicale.openshell-agents.svc.cluster.local:5232'
    args.date = None
    saved = kube_state()
    data = saved.get('data', {})
    if data.get('state'):
        save_state(args.state, json.loads(base64.b64decode(data['state'])))
    if args.action != 'seed':
        run(args)
        return
    password = Path('/input/password').read_text().rstrip('\r\n')
    if not password:
        raise ValueError('shared demo password must not be empty')
    # Adopt the previous branch's administrator instead of creating a new
    # password for an account that may already exist in Mattermost.
    previous = (kube_state(legacy=True).get('data', {}).get('state')
                if not data.get('admin') else None)
    encoded_admin = data.get('admin') or previous
    admin = json.loads(base64.b64decode(encoded_admin)) if encoded_admin else {
        'username': 'saw-lab-admin', 'password': secrets.token_urlsafe(32)}
    if not data.get('admin'):
        # Persist before account creation so a retried setup keeps its password.
        saved = kube_state({'metadata': {'resourceVersion': saved['metadata']['resourceVersion']},
                            'data': {'admin': base64.b64encode(json.dumps(admin).encode()).decode()}})
    chat = Client(args.mattermost_url)
    try:
        body, headers = chat.request('POST', '/api/v4/users/login',
                                    {'login_id': admin['username'], 'password': admin['password']})
    except RuntimeError as error:
        if not any(code in str(error) for code in ('HTTP 401', 'HTTP 404')):
            raise
        chat.json('POST', '/api/v4/users', {**admin, 'email': 'saw-lab-admin@example.test'})
        body, headers = chat.request('POST', '/api/v4/users/login',
                                    {'login_id': admin['username'], 'password': admin['password']})
    if 'system_admin' not in json.loads(body).get('roles', '').split() or not headers.get('Token'):
        raise RuntimeError('Shared demo administrator is unavailable')
    os.environ['MATTERMOST_ADMIN_TOKEN'] = headers['Token']
    os.environ['SAW_DEMO_PASSWORD'] = password
    try:
        run(args)
        run(argparse.Namespace(**{**vars(args), 'action': 'verify'}))
        state = json.loads(args.state.read_text())
        publish_chat(state['mattermost_token'])
    finally:
        if args.state.exists():
            kube_state({'metadata': {'resourceVersion': saved['metadata']['resourceVersion']},
                        'data': {'state': base64.b64encode(args.state.read_bytes()).decode()}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['seed', 'verify', 'challenge', 'reset'])
    parser.add_argument('--demo-id', default='rh1')
    parser.add_argument('--in-cluster', action='store_true', help='prepare the shared lab sources and publish the chat provider to Vault')
    parser.add_argument('--mailpit-url', default='http://127.0.0.1:8025')
    parser.add_argument('--mattermost-url', default='http://127.0.0.1:8065')
    parser.add_argument('--radicale-url', default='http://127.0.0.1:5232')
    parser.add_argument('--state', type=Path, default=Path('.saw-demo-state.json'))
    parser.add_argument('--date', type=dt.date.fromisoformat, help='fixture date; seed defaults to today UTC, other actions to the saved seed date')
    args = parser.parse_args()
    if not re.fullmatch('[a-z][a-z0-9-]{0,19}', args.demo_id):
        parser.error('demo-id must be a lowercase DNS label beginning with a letter (at most 20 characters)')
    try:
        if args.in_cluster:
            args.state = Path('/work/state.json')
            setup_shared(args)
        else:
            run(args)
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        print('Demo data error: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
