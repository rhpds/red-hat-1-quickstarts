#!/usr/bin/env python3
"""Vendor the IT self-service demo chart and its pinned dependencies."""
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

UPSTREAM = "https://github.com/rh-ai-quickstart/it-self-service-agent.git"
DEFAULT_REF = "v0.0.13"
spec = importlib.util.spec_from_file_location("update_rag", Path(__file__).with_name("update-rag.py"))
rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rag)

MOCK_SECRET = '''apiVersion: v1
kind: Secret
metadata:
  name: self-service-agent-servicenow-credentials
type: Opaque
stringData:
  servicenow-instance-url: http://self-service-agent-mock-servicenow:8080
  servicenow-api-key: now_mock_api_key
'''


def run(*args):
    subprocess.run(args, check=True)


def normalize_local_dependency(path):
    """Make Helm's locally packaged dependency stable across checkouts."""
    with tarfile.open(path, "r:gz") as source:
        entries = [(item, source.extractfile(item).read() if item.isfile() else None)
                   for item in source.getmembers()]
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as out:
            for item, data in sorted(entries, key=lambda entry: entry[0].name):
                item.mtime = 0
                item.pax_headers.pop("mtime", None)
                out.addfile(item, io.BytesIO(data) if data is not None else None)
    path.write_bytes(buffer.getvalue())


def update(source, ref, destination, dependency_dir=None):
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="selfsvc-update-", dir=destination) as temporary:
        tmp = Path(temporary)
        checkout, stage = tmp / "source", tmp / "stage"
        run("git", "clone", "--no-checkout", str(source), str(checkout))
        run("git", "-C", str(checkout), "checkout", "--detach", ref)
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        for name in ("helm/Chart.yaml", "helm/Chart.lock", "helm/values-test.yaml", "helm/values-demo.yaml", "test-email-server/test-email-server-greenmail.yaml"):
            if not (checkout / name).is_file():
                raise ValueError(f"Missing upstream file: {name}")
        chart = stage / "chart"
        shutil.copytree(checkout / "helm", chart)
        if dependency_dir:
            shutil.copytree(dependency_dir, chart / "charts", dirs_exist_ok=True)
        else:
            repo = tmp / "repositories.yaml"
            cache = tmp / "repository-cache"
            options = ("--repository-config", str(repo), "--repository-cache", str(cache))
            run("helm", "repo", "add", "zammad", "https://zammad.github.io/zammad-helm", *options)
            run("helm", "repo", "add", "rh-ai-quickstart", "https://rh-ai-quickstart.github.io/ai-architecture-charts", *options)
            run("helm", "dependency", "build", str(chart / "zammad"), "--skip-refresh", *options)
            run("helm", "dependency", "build", str(chart), "--skip-refresh", *options)
        rag.verify_dependencies(chart)
        rag.fix_llamastack_secret_reference(chart)
        for path in (chart / "charts").glob("ticketingZammad-*.tgz"):
            normalize_local_dependency(path)
        nested_packages = chart / "zammad/charts"
        if nested_packages.exists():
            shutil.rmtree(nested_packages)
        for name in ("init-job.yaml", "db-migration-job.yaml"):
            job = chart / "templates" / name
            contents = job.read_text()
            marker = "metadata:\n  name:"
            if contents.count(marker) != 1:
                raise ValueError(f"Upstream {name} changed; review Argo CD hook adaptation")
            job.write_text(contents.replace(marker, "metadata:\n  annotations:\n    argocd.argoproj.io/hook: Sync\n    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation\n  name:"))
        greenmail = (checkout / "test-email-server/test-email-server-greenmail.yaml").read_text()
        if "{{" in greenmail or "}}" in greenmail:
            raise ValueError("GreenMail manifest contains Helm template delimiters; review it before updating")
        (chart / "templates/greenmail.yaml").write_text(greenmail)
        (chart / "templates/servicenow-mock-secret.yaml").write_text(MOCK_SECRET)
        (stage / "source.json").write_text(json.dumps({"repository": UPSTREAM, "ref": ref, "commit": commit}, indent=2) + "\n")
        target, backup = destination / "it-selfsvc", tmp / "previous"
        if target.exists():
            target.rename(backup)
        try:
            stage.rename(target)
        except Exception:
            if backup.exists():
                backup.rename(target)
            raise
        print(f"Vendored IT self-service {commit}; review changes with git diff.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=UPSTREAM)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--dependency-dir", type=Path, help="directory containing locked chart packages")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        update(args.source, args.ref, args.destination.resolve(), args.dependency_dir)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"IT self-service refresh failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
