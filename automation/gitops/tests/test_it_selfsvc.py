import base64
import importlib.util
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_it_selfsvc", ROOT / "update-it-selfsvc.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class SelfServiceChartTests(unittest.TestCase):
    def test_provider_name_can_differ_from_model_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "values.yaml"
            path.write_text(yaml.safe_dump({"tenant": {"name": "7kzmd"}, "it-selfsvc": {
                "namespace": "user-7kzmd-it-svc", "model": {"name": "remotellm", "id": "vendor/model", "url": "https://example.invalid/v1", "apiToken": "test"}}}))
            output = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(path)], text=True)
            app = next(d for d in yaml.safe_load_all(output) if d and d.get("kind") == "Application" and d["metadata"]["name"].startswith("it-selfsvc-"))
            model = yaml.safe_load(app["spec"]["source"]["helm"]["values"])["global"]["models"]["remotellm"]
            self.assertEqual(model["id"], "vendor/model")

    def test_tenant_bootstrap_and_demo_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            values_file = Path(tmp) / "bootstrap.yaml"
            values_file.write_text(yaml.safe_dump({
                "tenant": {"name": "7kzmd"},
                "rag": {"namespace": "user-7kzmd-rag"},
                "it-selfsvc": {"namespace": "user-7kzmd-it-svc", "git": {"revision": "test-revision"},
                    "model": {"id": "llama-scout-17b", "url": "https://example.invalid/v1", "apiToken": "sample-token"},
                    "values": {"requestManagement": {"agentService": {"uvicornWorkers": 2},
                        "requestManager": {"uvicornWorkers": 2}, "integrationDispatcher": {"uvicornWorkers": 1}}}},
            }))
            output = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(values_file)], text=True)
            apps = {d["metadata"]["name"]: d for d in yaml.safe_load_all(output) if d and d.get("kind") == "Application"}
            self.assertEqual(set(apps), {"tenant-7kzmd", "it-selfsvc-7kzmd"})
            self.assertEqual(apps["tenant-7kzmd"]["spec"]["destination"]["namespace"], "user-7kzmd-rag")
            ignores = apps["tenant-7kzmd"]["spec"]["ignoreDifferences"]
            self.assertIn("/spec/host", next(i for i in ignores if i["kind"] == "Route")["jsonPointers"])
            self.assertEqual(next(i for i in ignores if i["kind"] == "Notebook")["name"], "rag-pipeline-notebook")
            app = apps["it-selfsvc-7kzmd"]
            self.assertEqual(app["spec"]["destination"]["namespace"], "user-7kzmd-it-svc")
            source = app["spec"]["source"]
            self.assertEqual(source["path"], "automation/gitops/it-selfsvc/chart")
            self.assertEqual(source["targetRevision"], "test-revision")
            self.assertEqual(source["helm"]["releaseName"], "self-service-agent")
            self.assertEqual(source["helm"]["valueFiles"], ["values-test.yaml", "values-demo.yaml"])
            overlay = yaml.safe_load(source["helm"]["values"])
            self.assertEqual(overlay["requestManagement"]["agentService"]["uvicornWorkers"], 2)
            self.assertEqual(overlay["requestManagement"]["requestManager"]["uvicornWorkers"], 2)
            self.assertEqual(overlay["requestManagement"]["integrationDispatcher"]["uvicornWorkers"], 1)
            self.assertEqual(overlay["security"]["email"]["smtpHost"], "test-email-server-smtp.user-7kzmd-it-svc.svc.cluster.local")
            child_values = Path(tmp) / "child.yaml"
            child_values.write_text(yaml.safe_dump(overlay))
            chart = ROOT / "it-selfsvc/chart"
            rendered = subprocess.check_output(["helm", "template", "self-service-agent", str(chart), "--namespace", "user-7kzmd-it-svc", "-f", str(chart / "values-test.yaml"), "-f", str(chart / "values-demo.yaml"), "-f", str(child_values)], text=True)
            resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(rendered) if isinstance(d, dict) and "kind" in d and "metadata" in d}
            for kind, name in (("Deployment", "test-email-server"), ("Route", "test-email-server-ui"), ("Service", "test-email-server-smtp"), ("Secret", "self-service-agent-servicenow-credentials"), ("Deployment", "self-service-agent-agent-service")):
                self.assertIn((kind, name), resources)
            for name in ("self-service-agent-init", "self-service-agent-db-migration"):
                self.assertEqual(resources[("Job", name)]["metadata"]["annotations"]["argocd.argoproj.io/hook"], "Sync")
            config = resources[("ConfigMap", "run-config")]["data"]["config.yaml"]
            self.assertIn("${env.SELFSVC_LLM_API_TOKEN}", config)
            self.assertNotIn("sample-token", config)
            secret = resources[("Secret", "llama-stack-env")]["data"]["SELFSVC_LLM_API_TOKEN"]
            self.assertEqual(base64.b64decode(secret).decode(), "sample-token")


class RefreshSelfServiceTests(unittest.TestCase):
    def test_refresh_and_failure_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest, deps = root / "source", root / "destination", root / "dependencies"
            source.mkdir()
            deps.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            for key, value in (("user.name", "Test"), ("user.email", "test@example.com")):
                subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
            files = {"helm/Chart.yaml": "name: fixture\nversion: 1.0.0\n",
                     "helm/Chart.lock": "dependencies:\n- name: llama-stack\n  version: 1.0.0\n",
                     "helm/values-test.yaml": "{}\n", "helm/values-demo.yaml": "{}\n",
                     "helm/templates/init-job.yaml": "metadata:\n  name: init\n",
                     "helm/templates/db-migration-job.yaml": "metadata:\n  name: migration\n",
                     "test-email-server/test-email-server-greenmail.yaml": "kind: ConfigMap\n"}
            for name, contents in files.items():
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
            with tarfile.open(deps / "llama-stack-1.0.0.tgz", "w:gz") as archive:
                for name, data in (("llama-stack/Chart.yaml", b"name: llama-stack\nversion: 1.0.0\n"),
                                   ("llama-stack/templates/deployment.yaml", b'for u in {{ $model.url }}/models#{{ $model.apiToken }}; do\n')):
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            def commit():
                subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
                subprocess.run(["git", "-C", str(source), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)
            commit()
            updater.update(source, "HEAD", dest, deps)
            app = dest / "it-selfsvc"
            def snapshot():
                return {str(p.relative_to(app)): p.read_bytes() for p in app.rglob("*") if p.is_file()}
            before = snapshot()
            self.assertIn("argocd.argoproj.io/hook: Sync", (app / "chart/templates/init-job.yaml").read_text())
            updater.update(source, "HEAD", dest, deps)
            self.assertEqual(snapshot(), before)
            (source / "test-email-server/test-email-server-greenmail.yaml").unlink()
            commit()
            with self.assertRaises(ValueError):
                updater.update(source, "HEAD", dest, deps)
            self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
