import json
import subprocess
import unittest
import uuid
from pathlib import Path


class LiveKillSwitchCliScriptTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _state_path(self) -> Path:
        return self._root() / ".tmp-tests" / "live-kill-switch-cli" / str(uuid.uuid4()) / "kill-switch.json"

    def test_enable_apply_writes_state(self) -> None:
        root = self._root()
        state_path = self._state_path()

        result = subprocess.run(
            [
                "bash",
                "scripts/set_live_kill_switch.sh",
                "--enable",
                "--reason",
                "unit_test_stop",
                "--actor",
                "test",
                "--path",
                str(state_path),
                "--apply",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["applied"])
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["submit_blocking_reason"], "kill_switch_enabled")
        self.assertTrue(state_path.exists())

    def test_disable_apply_requires_explicit_confirm(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/set_live_kill_switch.sh",
                "--disable",
                "--reason",
                "unit_test_release",
                "--actor",
                "test",
                "--path",
                str(self._state_path()),
                "--apply",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-disable", result.stderr)

    def test_disable_apply_with_confirm_writes_unblocked_state(self) -> None:
        root = self._root()
        state_path = self._state_path()

        result = subprocess.run(
            [
                "bash",
                "scripts/set_live_kill_switch.sh",
                "--disable",
                "--reason",
                "unit_test_release",
                "--actor",
                "test",
                "--path",
                str(state_path),
                "--apply",
                "--confirm-disable",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["applied"])
        self.assertFalse(payload["enabled"])
        self.assertIsNone(payload["submit_blocking_reason"])

    def test_dry_run_does_not_write(self) -> None:
        root = self._root()
        state_path = self._state_path()

        result = subprocess.run(
            [
                "bash",
                "scripts/set_live_kill_switch.sh",
                "--enable",
                "--reason",
                "unit_test_dry_run",
                "--actor",
                "test",
                "--path",
                str(state_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["applied"])
        self.assertFalse(state_path.exists())

    def test_path_must_stay_inside_repository(self) -> None:
        root = self._root()

        result = subprocess.run(
            [
                "bash",
                "scripts/set_live_kill_switch.sh",
                "--status",
                "--path",
                "/tmp/kill-switch.json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kill switch path must stay inside repository root", result.stderr)


if __name__ == "__main__":
    unittest.main()
