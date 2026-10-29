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

    def test_custom_repository_is_explicit(self):
        self.app["spec"]["source"]["repoURL"] = "http://git.test/repo.git"
        with self.assertRaises(ValueError):
            live_test.validate_gitops_app(self.app, "rag", self.path, "test", "commit-a")
        live_test.validate_gitops_app(self.app, "rag", self.path, "test", "commit-a", "http://git.test/repo.git")

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

    def test_collections_reject_failed_or_missing_files(self):
        namespace = {}
        exec(live_test.VALIDATE_STORES, namespace)
        validate = namespace["validate_stores"]
        store = {"name": "hr", "file_counts": {"completed": 1, "failed": 0}}
        validate([store], ["hr"])
        for counts in ({"completed": 1, "failed": 1}, {"completed": 0},
                       {"completed": 1, "in_progress": 1}, {"completed": 1, "cancelled": 1}):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                validate([{"name": "hr", "file_counts": counts}], ["hr"])
        with self.assertRaises(ValueError):
            validate([], ["hr"])
