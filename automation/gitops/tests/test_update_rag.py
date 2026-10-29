import hashlib
import importlib.util
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "update-rag.py"
spec = importlib.util.spec_from_file_location("update_rag", SCRIPT)
update_rag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_rag)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def snapshot(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.dest, self.packages = root / "source", root / "dest", root / "packages"
        self.source.mkdir()
        self.packages.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        git(self.source, "config", "user.email", "test@example.com")
        git(self.source, "config", "user.name", "Test")
        self.write("infra/README.md", "infra\n")
        self.write("tenant/bootstrap/values.yaml", "rag:\n  git:\n    url: https://github.com/rh-ai-quickstart/RAG.git\n    path: deploy/helm/rag\n")
        self.write("tenant/old.txt", "old\n")
        self.write("deploy/helm/rag/Chart.lock", "dependencies:\n- name: sample\n  version: 1.0.0\n")
        self.write("deploy/helm/rag/.gitignore", "charts/\n")
        self.write("tests/e2e/README.md", "e2e\n")
        self.write("tests/e2e_ui/test_example.py", "# example\n")
        self.write("tests/integration/llamastack/test_example.py", "# example\n")
        self.write("tests/README.md", "tests\n")
        self.write("LICENSE", "fixture\n")
        data = b"name: sample\nversion: 1.0.0\n"
        with tarfile.open(self.packages / "sample-1.0.0.tgz", "w:gz") as tf:
            info = tarfile.TarInfo("sample/Chart.yaml")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        (self.dest / "infra/bootstrap").mkdir(parents=True)
        (self.dest / "infra/bootstrap/local").write_text("keep")
        (self.dest / "unrelated").write_text("keep")
        self.commit()

    def write(self, name, contents):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def commit(self):
        git(self.source, "add", "-A")
        git(self.source, "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        return git(self.source, "rev-parse", "HEAD")

    def refresh(self):
        update_rag.update(self.source, "HEAD", self.dest, self.packages)

    def test_refresh_and_repeatability(self):
        commit = git(self.source, "rev-parse", "HEAD")
        self.refresh()
        self.assertIn(commit, (self.dest / "rag-source.json").read_text())
        values = (self.dest / "tenant/bootstrap/values.yaml").read_text()
        self.assertIn(update_rag.LOCAL, values)
        self.assertIn(update_rag.CHART_PATH, values)
        self.assertEqual((self.dest / "upstream-rag-tests/e2e/README.md").read_text(), "e2e\n")
        before = snapshot(self.dest)
        self.refresh()
        self.assertEqual(before, snapshot(self.dest))
        (self.source / "tenant/old.txt").unlink()
        self.write("infra/README.md", "updated\n")
        self.commit()
        self.refresh()
        self.assertFalse((self.dest / "tenant/old.txt").exists())
        self.assertEqual((self.dest / "infra/README.md").read_text(), "updated\n")
        self.assertEqual((self.dest / "infra/bootstrap/local").read_text(), "keep")
        self.assertEqual((self.dest / "unrelated").read_text(), "keep")

    def test_missing_source_and_dependency_leave_destination_unchanged(self):
        self.refresh()
        before = snapshot(self.dest)
        (self.source / "tenant/bootstrap/values.yaml").unlink()
        self.commit()
        with self.assertRaises(ValueError):
            self.refresh()
        self.assertEqual(before, snapshot(self.dest))
        git(self.source, "reset", "--hard", "HEAD~1")
        (self.packages / "sample-1.0.0.tgz").rename(self.packages / "sample-2.0.0.tgz")
        with self.assertRaises(FileNotFoundError):
            self.refresh()
        self.assertEqual(before, snapshot(self.dest))

    def test_failed_dependency_build_leaves_destination_unchanged(self):
        self.refresh()
        before = snapshot(self.dest)
        original_run = update_rag.run

        def fail_helm(*args):
            if args[0] == "helm":
                raise subprocess.CalledProcessError(1, args)
            original_run(*args)

        with mock.patch.object(update_rag, "run", side_effect=fail_helm):
            with self.assertRaises(subprocess.CalledProcessError):
                update_rag.update(self.source, "HEAD", self.dest)
        self.assertEqual(before, snapshot(self.dest))

    def test_llamastack_secret_reference_is_quoted_and_repeatable(self):
        chart = Path(self.temp.name) / "chart"
        (chart / "charts").mkdir(parents=True)
        (chart / "Chart.lock").write_text("dependencies:\n- name: llama-stack\n  version: 1.0.0\n")
        archive = chart / "charts/llama-stack-1.0.0.tgz"
        content = b'for url_data in {{ $model.url }}/models#{{ $model.apiToken }}; do\n'
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo("llama-stack/templates/deployment.yaml")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        update_rag.fix_llamastack_secret_reference(chart)
        before = archive.read_bytes()
        with tarfile.open(archive, "r:gz") as tf:
            self.assertIn(b"'{{ $model.url }}/models#{{ $model.apiToken }}'", tf.extractfile("llama-stack/templates/deployment.yaml").read())
        update_rag.fix_llamastack_secret_reference(chart)
        self.assertEqual(before, archive.read_bytes())


if __name__ == "__main__":
    unittest.main()
