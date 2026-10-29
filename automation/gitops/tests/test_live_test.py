import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "e2e/live-test.py"
spec = importlib.util.spec_from_file_location("live_test", path)
live_test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live_test)


class GitOpsValidationTests(unittest.TestCase):
    def setUp(self):
        self.path = "automation/gitops/tenant/deploy/helm/rag"
        self.app = {"spec": {"source": {"repoURL": live_test.REPO + ".git", "path": self.path},
                             "destination": {"namespace": "test"}},
                    "status": {"sync": {"status": "Synced", "revision": "commit-a"}, "health": {"status": "Healthy"}}}

    def test_healthy_app(self):
        self.assertEqual(live_test.validate_gitops_app(self.app, "rag", self.path, "test", "commit-a")["path"], self.path)

    def test_rejects_wrong_source_health_or_namespace(self):
        for change in ("repo", "path", "sync", "health", "namespace", "revision"):
            with self.subTest(change=change):
                self.setUp()
                if change == "repo": self.app["spec"]["source"]["repoURL"] = "https://example.com/other.git"
                if change == "path": self.app["spec"]["source"]["path"] = "deploy/helm/rag"
                if change == "sync": self.app["status"]["sync"]["status"] = "OutOfSync"
                if change == "health": self.app["status"]["health"]["status"] = "Degraded"
                if change == "namespace": self.app["spec"]["destination"]["namespace"] = "other"
                if change == "revision": self.app["status"]["sync"]["revision"] = "commit-b"
                with self.assertRaises(ValueError):
                    live_test.validate_gitops_app(self.app, "rag", self.path, "test", "commit-a")


class IngestionValidationTests(unittest.TestCase):
    def test_latest_run_must_succeed(self):
        def run(timestamp, status):
            return {"metadata": {"creationTimestamp": timestamp, "annotations": {"pipelines.kubeflow.org/run_name": "hr-run"}}, "status": {"phase": status}}
        live_test.validate_ingestion([run("1", "Failed"), run("2", "Succeeded")], ["hr"])
        with self.assertRaises(ValueError):
            live_test.validate_ingestion([run("1", "Succeeded"), run("2", "Failed")], ["hr"])
        with self.assertRaises(ValueError):
            live_test.validate_ingestion([], ["hr"])
