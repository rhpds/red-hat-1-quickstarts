#!/usr/bin/env python3
"""Vendor the multimodal compliance monitor Helm chart and dependencies."""
import argparse
import gzip
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor.git"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("update_rag", Path(__file__).with_name("update-rag.py"))
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)


def run(*args):
    subprocess.run(args, check=True)


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"Upstream {path.name} changed; review the GitOps adaptation")
    path.write_text(text.replace(old, new))


def adapt_chart(chart):
    # All jobs and workloads start in wave zero. The uploader waits for storage,
    # and the video deployment waits for its uploaded data. Later waves would
    # deadlock because Argo waits for those deployments before advancing.
    init = chart / "templates/init-data.yaml"
    for marker in ('  name: {{ include "ppe-compliance-monitor.fullname" . }}-init-data-model',
                   '  name: {{ printf "%s-s3-%s" (include "ppe-compliance-monitor.fullname" .) $jobHash | trunc 63 | trimSuffix "-" }}'):
        replace_once(init, marker, marker + '\n  annotations:\n    argocd.argoproj.io/hook: Sync\n    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded')
    for ttl in ('  ttlSecondsAfterFinished: 300\n', '  ttlSecondsAfterFinished: 600\n'):
        replace_once(init, ttl, '')
    runtime = chart / "templates/runtime-deployer.yaml"
    replace_once(runtime, '    argocd.argoproj.io/sync-wave: "1"',
                 '    argocd.argoproj.io/sync-wave: "1"\n    argocd.argoproj.io/hook: Sync\n    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded')
    replace_once(runtime, 'value: {{ .Values.modelServing.kserve.image | quote }}',
                 'value: {{ include "rh1.pinnedImage" .Values.modelServing.kserve.image | quote }}')
    for filename in ("backend-deployment.yaml", "eval-job.yaml"):
        replace_once(chart / "templates" / filename,
                     'value: {{ .Values.openai.apiToken | quote }}',
                     'valueFrom:\n                secretKeyRef:\n                  name: {{ include "ppe-compliance-monitor.fullname" . }}-openai\n                  key: api-token')
    backend = chart / "templates/backend-deployment.yaml"
    replace_once(backend, '  template:\n    metadata:\n      labels:',
                 '  template:\n    metadata:\n      annotations:\n        checksum/openai-token: {{ .Values.openai.apiToken | sha256sum | quote }}\n      labels:')
    (chart / "templates/openai-secret.yaml").write_text('''apiVersion: v1
kind: Secret
metadata:
  name: {{ include "ppe-compliance-monitor.fullname" . }}-openai
type: Opaque
stringData:
  api-token: {{ .Values.openai.apiToken | quote }}
''')


def normalize_package(path):
    with tarfile.open(path, "r:gz") as source:
        entries = [(item, source.extractfile(item).read() if item.isfile() else None) for item in source.getmembers()]
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as output:
            for item, data in sorted(entries, key=lambda entry: entry[0].name):
                item.mtime = 0
                item.pax_headers.pop("mtime", None)
                output.addfile(item, io.BytesIO(data) if data is not None else None)
    path.write_bytes(buffer.getvalue())


def update(source, ref, destination, dependency_dir=None):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="multimodal-update-", dir=destination) as temporary:
        tmp = Path(temporary)
        checkout, stage = tmp / "source", tmp / "stage"
        run("git", "clone", "--no-checkout", str(source), str(checkout))
        run("git", "-C", str(checkout), "checkout", "--detach", ref)
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        if not (checkout / "LICENSE").is_file():
            raise ValueError("Missing upstream LICENSE")
        for name in ("ppe-compliance-monitor", "label-studio", "jupyter-training"):
            if not (checkout / "deploy/helm" / name / "Chart.yaml").is_file():
                raise ValueError(f"Missing upstream chart: {name}")
            shutil.copytree(checkout / "deploy/helm" / name, tmp / "helm" / name)
        chart = tmp / "helm/ppe-compliance-monitor"
        if not (chart / "Chart.lock").is_file():
            raise ValueError("Missing upstream Chart.lock")
        if dependency_dir:
            shutil.copytree(dependency_dir, chart / "charts", dirs_exist_ok=True)
        else:
            options = ("--repository-config", str(tmp / "repositories.yaml"), "--repository-cache", str(tmp / "repository-cache"))
            run("helm", "repo", "add", "rh-ai-quickstart", "https://rh-ai-quickstart.github.io/ai-architecture-charts", *options)
            run("helm", "dependency", "build", str(chart), "--skip-refresh", *options)
        rag.verify_dependencies(chart)
        for name in ("label-studio", "jupyter-training"):
            for package in (chart / "charts").glob(name + "-*.tgz"):
                normalize_package(package)
        adapt_chart(chart)
        rag.image_pins.apply(chart)
        stage.mkdir()
        shutil.copytree(chart, stage / "chart")
        shutil.copy2(checkout / "LICENSE", stage / "LICENSE")
        (stage / "source.json").write_text(json.dumps({"repository": UPSTREAM, "ref": ref, "commit": commit}, indent=2) + "\n")
        target, backup = destination / "tenant/multimodal", tmp / "previous"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except Exception:
            if backup.exists():
                backup.rename(target)
            raise
        print(f"Vendored multimodal compliance monitor {commit}; review changes with git diff.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=UPSTREAM)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--dependency-dir", type=Path, help="directory containing locked chart packages")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        update(args.source, args.ref, args.destination.resolve(), args.dependency_dir)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Multimodal refresh failed: {exc}\n")


if __name__ == "__main__":
    main()
