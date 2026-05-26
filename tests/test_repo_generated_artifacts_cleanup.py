import json
import subprocess
import tempfile
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cleanup_repo_generated_artifacts.sh"


class RepoGeneratedArtifactsCleanupTests(unittest.TestCase):
    def _run_cleanup(self, workspace: Path, *, apply: bool = False) -> dict:
        runtime = workspace / "runtime-data"
        command = [
            "bash",
            str(SCRIPT),
            "--workspace-root",
            str(workspace),
            "--runtime-data-dir",
            str(runtime),
        ]
        if apply:
            command.append("--apply")
        proc = subprocess.run(command, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        return json.loads(proc.stdout)

    def test_dry_run_reports_targets_without_removing_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            (workspace / ".tmp-tests" / "old").mkdir(parents=True)
            (workspace / ".tmp-tests" / "old" / "artifact.txt").write_text("old\n", encoding="utf-8")
            (workspace / ".tmp-tests" / "codex-ops").mkdir(parents=True)
            (workspace / ".tmp-tests" / "codex-ops" / "draft.txt").write_text("keep\n", encoding="utf-8")
            (workspace / "app" / "example" / "__pycache__").mkdir(parents=True)
            (workspace / "app" / "example" / "__pycache__" / "x.pyc").write_bytes(b"x")
            (workspace / "Microsoft.PowerShell.CoreFileSystem::tmp").mkdir(parents=True)

            report = self._run_cleanup(workspace)

            self.assertEqual(report["status"], "dry_run")
            self.assertGreaterEqual(report["target_count"], 3)
            self.assertTrue((workspace / ".tmp-tests" / "old" / "artifact.txt").exists())
            self.assertTrue((workspace / ".tmp-tests" / "codex-ops" / "draft.txt").exists())

    def test_apply_removes_generated_artifacts_but_keeps_codex_ops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            (workspace / ".tmp-tests" / "old").mkdir(parents=True)
            (workspace / ".tmp-tests" / "old" / "artifact.txt").write_text("old\n", encoding="utf-8")
            (workspace / ".tmp-tests" / "codex-ops").mkdir(parents=True)
            (workspace / ".tmp-tests" / "codex-ops" / "draft.txt").write_text("keep\n", encoding="utf-8")
            (workspace / "scripts" / "__pycache__").mkdir(parents=True)
            (workspace / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"x")
            (workspace / "app" / "risk" / "__pycache__").mkdir(parents=True)
            (workspace / "app" / "risk" / "__pycache__" / "x.pyc").write_bytes(b"x")
            (workspace / "Microsoft.PowerShell.CoreFileSystem::tmp").mkdir(parents=True)

            report = self._run_cleanup(workspace, apply=True)

            self.assertEqual(report["status"], "applied")
            self.assertGreaterEqual(report["removed_count"], 3)
            self.assertFalse((workspace / ".tmp-tests" / "old").exists())
            self.assertFalse((workspace / "scripts" / "__pycache__").exists())
            self.assertFalse((workspace / "Microsoft.PowerShell.CoreFileSystem::tmp").exists())
            self.assertTrue((workspace / "app" / "risk" / "__pycache__" / "x.pyc").exists())
            self.assertTrue((workspace / ".tmp-tests" / "codex-ops" / "draft.txt").exists())


if __name__ == "__main__":
    unittest.main()
