#!/usr/bin/env python3
"""Refresh the locally vendored RAG GitOps content."""
import argparse
import gzip
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

UPSTREAM = "https://github.com/rh-ai-quickstart/RAG.git"
LOCAL = "https://github.com/rhpds/red-hat-1-quickstarts.git"
CHART_PATH = "automation/gitops/tenant/deploy/helm/rag"
RAG_IGNORE_DIFFERENCES = '''  ignoreDifferences:
    - group: route.openshift.io
      kind: Route
      jsonPointers:
        - /spec/host
        - /spec/alternateBackends
    - group: kubeflow.org
      kind: Notebook
      name: rag-pipeline-notebook
      jqPathExpressions:
        - '.spec.template.spec.containers[].env[] | select(.name == "PIP_CERT" or .name == "REQUESTS_CA_BUNDLE" or .name == "SSL_CERT_FILE" or .name == "PIPELINES_SSL_SA_CERTS" or .name == "GIT_SSL_CAINFO")'
        - '.spec.template.spec.containers[].volumeMounts[] | select(.name == "trusted-ca")'
        - '.spec.template.spec.volumes[] | select(.name == "trusted-ca")'
        - '.spec.template.spec.initContainers[] | select(.name == "clone-notebook-repo") | .resources'
'''


def run(*args):
    subprocess.run(args, check=True)


def verify_dependencies(chart):
    lock = yaml.safe_load((chart / "Chart.lock").read_text())
    for dep in lock["dependencies"]:
        archive = chart / "charts" / f'{dep["name"]}-{dep["version"]}.tgz'
        with tarfile.open(archive, "r:gz") as tf:
            metadata = yaml.safe_load(tf.extractfile(f'{dep["name"]}/Chart.yaml'))
        if metadata.get("name") != dep["name"] or str(metadata.get("version")) != str(dep["version"]):
            raise ValueError(f"Incorrect chart metadata in {archive.name}")


def fix_llamastack_secret_reference(chart):
    """Quote model URLs so the init shell treats ${env.NAME} as data."""
    lock = yaml.safe_load((chart / "Chart.lock").read_text())
    for dep in lock["dependencies"]:
        if dep["name"] != "llama-stack":
            continue
        archive = chart / "charts" / f'llama-stack-{dep["version"]}.tgz'
        old = b'{{ $model.url }}/models#{{ $model.apiToken }}'
        new = b"'{{ $model.url }}/models#{{ $model.apiToken }}'"
        with tarfile.open(archive, "r:gz") as source:
            entries = [(item, source.extractfile(item).read() if item.isfile() else None)
                       for item in source.getmembers()]
        buffer = io.BytesIO()
        found = False
        with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as out:
                for item, data in entries:
                    if item.name == "llama-stack/templates/deployment.yaml":
                        if data.count(old) == 1 and new not in data:
                            data = data.replace(old, new)
                        elif data.count(new) != 1:
                            raise ValueError("Llama Stack model readiness template changed; review the local patch")
                        item.size = len(data)
                        found = True
                    out.addfile(item, io.BytesIO(data) if data is not None else None)
        if not found:
            raise ValueError("Llama Stack deployment template not found")
        archive.write_bytes(buffer.getvalue())


def update(source, ref, destination, dependency_dir=None):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rag-update-", dir=destination) as tmp:
        tmp = Path(tmp)
        checkout, stage = tmp / "source", tmp / "stage"
        run("git", "clone", "--no-checkout", str(source), str(checkout))
        run("git", "-C", str(checkout), "checkout", "--detach", ref)
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        for name in ("infra", "tenant/bootstrap", "deploy/helm/rag", "tests/e2e", "tests/e2e_ui", "tests/integration/llamastack"):
            if not (checkout / name).is_dir():
                raise ValueError(f"Missing upstream directory: {name}")
        if not (checkout / "tenant/bootstrap/values.yaml").is_file():
            raise ValueError("Missing upstream tenant bootstrap values.yaml")
        shutil.copytree(checkout / "infra", stage / "infra")
        shutil.copytree(checkout / "tenant", stage / "tenant")
        # Local bootstrap extensions are maintained separately from upstream RAG.
        local_extension = destination / "tenant/bootstrap/templates/application-it-selfsvc.yaml"
        if local_extension.exists():
            shutil.copy2(local_extension, stage / "tenant/bootstrap/templates/application-it-selfsvc.yaml")
        rag_application = stage / "tenant/bootstrap/templates/application-rag.yaml"
        if rag_application.exists():
            original = rag_application.read_text()
            old = "name: {{ .Values.tenant.name }}"
            if original.count(old) != 1:
                raise ValueError("Upstream RAG Application name changed; review the tenant-name adaptation")
            original = original.replace(old, "name: tenant-{{ .Values.tenant.name }}")
            if original.count("  syncPolicy:\n") != 1:
                raise ValueError("Upstream RAG Application sync policy changed; review the drift adaptations")
            rag_application.write_text(original.replace("  syncPolicy:\n", RAG_IGNORE_DIFFERENCES + "  syncPolicy:\n"))
        upstream_tests = stage / "upstream-rag-tests"
        shutil.copytree(checkout / "tests/e2e", upstream_tests / "e2e")
        shutil.copytree(checkout / "tests/e2e_ui", upstream_tests / "e2e_ui")
        shutil.copytree(checkout / "tests/integration/llamastack", upstream_tests / "integration/llamastack")
        shutil.copy2(checkout / "tests/README.md", upstream_tests / "README.md")
        shutil.copy2(checkout / "LICENSE", upstream_tests / "LICENSE")
        local_infra = destination / "infra/bootstrap"
        if local_infra.exists():
            shutil.copytree(local_infra, stage / "infra/bootstrap", dirs_exist_ok=True)
        chart = stage / "tenant/deploy/helm/rag"
        shutil.copytree(checkout / "deploy/helm/rag", chart, dirs_exist_ok=True)
        values = stage / "tenant/bootstrap/values.yaml"
        raw = values.read_text()
        current = yaml.safe_load(raw)["rag"]["git"]
        for key, new in (("url", LOCAL), ("path", CHART_PATH)):
            old = str(current[key])
            pattern = r"(?m)^(\s*" + key + r":\s*)[\"']?" + re.escape(old) + r"[\"']?\s*$"
            raw, count = re.subn(pattern, lambda m: m.group(1) + new, raw)
            if count != 1:
                raise ValueError(f"Could not uniquely adapt rag.git.{key}")
        values.write_text(raw)
        ignore = chart / ".gitignore"
        if ignore.exists():
            ignore.write_text("\n".join(line for line in ignore.read_text().splitlines() if line.strip() not in ("charts/", "/charts/")) + "\n")
        if dependency_dir:
            shutil.copytree(dependency_dir, chart / "charts", dirs_exist_ok=True)
        else:
            run("helm", "dependency", "build", str(chart))
        verify_dependencies(chart)
        fix_llamastack_secret_reference(chart)
        (stage / "rag-source.json").write_text(json.dumps({"repository": UPSTREAM, "commit": commit}, indent=2) + "\n")
        # Keep backups until all staged paths are installed, and roll back on failure.
        installed, backups = [], []
        try:
            for name in ("infra", "tenant", "upstream-rag-tests", "rag-source.json"):
                target, backup = destination / name, tmp / (name + ".backup")
                if target.exists():
                    target.rename(backup)
                    backups.append((backup, target))
                (stage / name).rename(target)
                installed.append(target)
        except Exception:
            for target in reversed(installed):
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            for backup, target in reversed(backups):
                backup.rename(target)
            raise
        print(f"Vendored RAG {commit}; review changes with git diff.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="upstream branch, tag, or commit")
    parser.add_argument("--source", default=UPSTREAM, help="Git URL or local checkout")
    parser.add_argument("--dependency-dir", type=Path, help="directory containing the locked chart packages")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        update(args.source, args.ref, args.destination.resolve(), args.dependency_dir)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, yaml.YAMLError, tarfile.TarError) as exc:
        print(f"RAG refresh failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
