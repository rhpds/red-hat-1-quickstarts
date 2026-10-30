import json
import os
import pathlib
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request

vault_url = 'https://vault.vault.svc:8200/v1/secret/data/' + os.environ['SAW_SSH_VAULT_PATH']
token = pathlib.Path('/vault-token/token').read_text().strip()
context = ssl.create_default_context(cafile='/ca/service-ca.crt')
headers = {'X-Vault-Token': token, 'Content-Type': 'application/json'}


def current():
    try:
        with urllib.request.urlopen(urllib.request.Request(vault_url, headers=headers), context=context, timeout=30) as response:
            return json.load(response)['data']['data']
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        if code == 404:
            return None
        raise


def validate(value):
    if not value or not value.get('private_key') or not value.get('public_key'):
        raise SystemExit('Vault SSH entry is incomplete; refusing to replace it')


existing = current()
if existing is not None:
    validate(existing)
    print('Existing SSH key preserved')
else:
    os.umask(0o077)
    with tempfile.TemporaryDirectory(dir='/tmp') as tmp:
        key = pathlib.Path(tmp) / 'id_ed25519'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'openshell-sandbox', '-f', str(key)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        data = {'private_key': key.read_text(), 'public_key': key.with_suffix('.pub').read_text().strip()}
        request = urllib.request.Request(vault_url, data=json.dumps({'options': {'cas': 0}, 'data': data}).encode(), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, context=context, timeout=30):
                pass
        except urllib.error.HTTPError as error:
            # A competing provisioner may have won the create-only write.
            code = error.code
            error.close()
            if code != 400:
                raise
            validate(current())
            print('Another provisioner created the SSH key; preserved it')
        else:
            print('Created SSH key in Vault')
