#!/usr/bin/env python3
"""Vendor a reviewed Secure Agent Workspace revision for local GitOps."""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

UPSTREAM = 'https://github.com/validatedpatterns-sandbox/secure-agent-workspace.git'
DESTINATION = Path(__file__).resolve().parent / 'tenant/saw'
PATH_PREFIX = 'automation/gitops/tenant/saw/charts/'
PINS = {
    'registry.redhat.io/rhel9/postgresql-16:latest': 'sha256:9223bb5f0745e66f0e4204ff87d4d1a5283f3726e9b7d9b71d7bdb2a650fc218',
    'registry.access.redhat.com/ubi9/python-311:latest': 'sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c',
    'ghcr.io/validatedpatterns-sandbox/governance-interceptor:v0.1.2': 'sha256:253b58d070d3ed341287fcbab44684d84a437fcb9f26be5834ebf554a40ec22f',
    'registry.fedoraproject.org/fedora:44': 'sha256:b414c09be79dd1f32529b55b096b6bb30435d82ee16fbdbbabf8985eb5f86db0',
    'quay.io/gkrumbach07/openshell-dashboard:latest': 'sha256:873d4379edfa42a7ff56451a98d4f448c2b3a7085c7beb74d1368606addced80',
    'quay.io/oauth2-proxy/oauth2-proxy:v7.9.0': 'sha256:37c1570c0427e02fc7c947ef2c04e8995b8347b7abc9fcf1dbb4e376a4b221a7',
    'ghcr.io/validatedpatterns-sandbox/nemoclaw-cli:latest': 'sha256:3283cf580e8187a53371c5cabc0557abf9845066a871cbd6596a500a9bcd04a0',
    'ghcr.io/validatedpatterns-sandbox/nemoclaw-sandbox:latest': 'sha256:28457eec59e71eca310cd72fc4b57c71506c3fce4c30f2636a237dca85725dbd',
    'quay.io/opendatahub/odh-openshell-gateway:v0.1.2-rhaiv.6': 'sha256:7bd1357f8b4c293ea6527dee2035e26dcca02fb9a87fb1521a0cd9255ec7d9fc',
    'quay.io/opendatahub/odh-openshell-supervisor:v0.1.2-rhaiv.6': 'sha256:f2178e5ef0948c145b7cc3a7ab3b3238aaf36d2c13a2826aae39b601e987bd7b',
    'node:22-trixie-slim': 'sha256:2117f713a417f3aff682ac8f5bc2ebbdf1beed51f36e67ab1e0fd3866b6d2d8f',
    'rust:1.94-bookworm': 'sha256:6ae102bdbf528294bc79ad6e1fae682f6f7c2a6e6621506ba959f9685b308a55',
    'registry.access.redhat.com/ubi9-micro:latest': 'sha256:5be877a2a280ae36eb9ab80ca4efb28bbf77c57abbba38137cdc37a03b8465e6',
    'ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.133': 'sha256:6dd56f1607f5d29d35731191052b6a317cff5fc2659f71b35695a76e0f36dc6a',
}


def update(source, ref, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='saw-update-', dir=destination.parent) as temporary:
        root = Path(temporary)
        checkout, stage, backup = root / 'source', root / 'stage', root / 'previous'
        subprocess.run(['git', 'clone', '--no-checkout', str(source), str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--detach', ref], check=True)
        commit = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        required = ['saw-users', 'openshell-saw', 'saw-bom', 'pattern-secrets', 'openshell-keycloak', 'openshift-cnv', 'governance-policy', 'governance-interceptor', 'openshell-rhdh']
        for name in required:
            if not (checkout / 'charts' / name / 'Chart.yaml').is_file():
                raise ValueError(f'Missing upstream chart {name}')
        shutil.copytree(checkout / 'charts', stage / 'charts')
        shutil.copytree(checkout / 'image-builder-charts/helm', stage / 'image-builders')
        shutil.copytree(checkout / 'overrides/governance-profiles', stage / 'governance-profiles')
        for relative in ['charts/saw-users/templates/applications.yaml', 'charts/openshell-rhdh/templates/applicationset.yaml']:
            file = stage / relative
            original = file.read_text()
            updated = original.replace('"charts/', '"' + PATH_PREFIX).replace('path: charts/', 'path: ' + PATH_PREFIX)
            if updated == original:
                raise ValueError(f'Upstream chart paths changed in {relative}; review the integration')
            file.write_text(updated)
        postgres = stage / 'charts/openshell-keycloak/templates/postgres.yaml'
        text = postgres.read_text()
        for field in ('username', 'password'):
            old = '{{ .Values.postgres.' + field + ' }}'
            if text.count(old) != 1:
                raise ValueError(f'Upstream Keycloak PostgreSQL {field} template changed; review the integration')
            text = text.replace(old, '{{ .Values.postgres.' + field + ' | quote }}')
        postgres.write_text(text)
        for file in stage.rglob('*.yaml'):
            text = file.read_text()
            for image, digest in PINS.items():
                text = text.replace(image + '@' + digest, image).replace(image, image + '@' + digest)
            file.write_text(text)
        if (destination / 'README.md').is_file():
            shutil.copy2(destination / 'README.md', stage / 'README.md')
        (stage / 'source.json').write_text(json.dumps({'repository': UPSTREAM, 'ref': ref, 'commit': commit}, indent=2) + '\n')
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except Exception:
            if backup.exists():
                backup.rename(destination)
            raise
        print(f'Vendored Secure Agent Workspace {commit}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=UPSTREAM)
    parser.add_argument('--ref', default='main')
    parser.add_argument('--destination', type=Path, default=DESTINATION)
    args = parser.parse_args()
    update(args.source, args.ref, args.destination)


if __name__ == '__main__':
    main()
