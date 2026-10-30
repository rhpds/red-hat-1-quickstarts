import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("update_multimodal", ROOT / "update-multimodal.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class MultimodalChartTests(unittest.TestCase):
    def test_optional_application_and_cpu_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = Path(tmp) / "values.yaml"
            values.write_text(yaml.safe_dump({"tenant": {"name": "7kzmd"}, "ppe": {
                "namespace": "user-7kzmd-ppe", "values": {
                    "openai": {"apiToken": "test-token", "apiEndpoint": "https://example.invalid/v1", "model": "model"},
                    "s3Credentials": {"accessKeyId": "test-access", "secretAccessKey": "test-secret", "uiUsername": "user", "uiPassword": "pass"}}}}))
            rendered = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(values)], text=True)
            app = next(d for d in yaml.safe_load_all(rendered) if d and d.get("kind") == "Application" and d["metadata"]["name"] == "ppe-7kzmd")
            self.assertEqual(app["spec"]["destination"]["namespace"], "user-7kzmd-ppe")
            self.assertEqual(app["spec"]["source"]["path"], "automation/gitops/tenant/multimodal/chart")
            child = Path(tmp) / "child.yaml"
            child.write_text(app["spec"]["source"]["helm"]["values"])
            chart = subprocess.check_output(["helm", "template", "ppe-7kzmd", str(ROOT / "tenant/multimodal/chart"), "--namespace", "user-7kzmd-ppe", "-f", str(child)], text=True)
            resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(chart) if isinstance(d, dict) and "kind" in d and "metadata" in d}
            backend = resources[("Deployment", "ppe-7kzmd-ppe-compliance-monitor-backend")]
            env = {item["name"]: item for item in backend["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(env["RUNTIME_TYPE"]["value"], "openvino")
            self.assertEqual(env["OPENAI_API_TOKEN"]["valueFrom"]["secretKeyRef"]["key"], "api-token")
            self.assertNotIn("test-token", yaml.safe_dump(backend))
            self.assertEqual(resources[("Secret", "ppe-7kzmd-ppe-compliance-monitor-openai")]["stringData"]["api-token"], "test-token")
            self.assertIn("checksum/openai-token", backend["spec"]["template"]["metadata"]["annotations"])
            values.write_text("ppe: {}\n")
            rendered = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(values)], text=True)
            self.assertFalse(any(d and d.get("metadata", {}).get("name", "").startswith("ppe-") for d in yaml.safe_load_all(rendered)))


class MultimodalRefreshTests(unittest.TestCase):
    def test_failed_refresh_preserves_existing_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, dest = root / "source", root / "destination"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid")):
                subprocess.run(["git", "-C", str(source), "config", key, value], check=True)
            (source / "README.md").write_text("missing chart\n")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"], check=True)
            (dest / "tenant/multimodal").mkdir(parents=True)
            (dest / "tenant/multimodal/source.json").write_text("keep\n")
            with self.assertRaises(ValueError):
                updater.update(source, "HEAD", dest)
            self.assertEqual((dest / "tenant/multimodal/source.json").read_text(), "keep\n")


if __name__ == "__main__":
    unittest.main()
