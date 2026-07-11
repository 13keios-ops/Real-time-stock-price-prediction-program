import subprocess
import tempfile
import unittest
from pathlib import Path


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class KisEnvRestoreScriptTests(unittest.TestCase):
    def test_live_readonly_preparation_preserves_paper_mode_and_disables_live_orders(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".tmp-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kis-env-restore-", dir=temp_root) as tmp:
            workspace = Path(tmp)
            (workspace / ".env.example").write_text(
                "TRADING_MODE=paper\nALLOW_LIVE_ORDERS=true\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "bash",
                    "scripts/restore_kis_env_interactive.sh",
                    "--trading-mode",
                    "live",
                    "--include-account-fields",
                    "--read-only-preparation",
                    "--workspace-root",
                    str(workspace),
                ],
                cwd=root,
                input="live-key\nlive-secret\n12345678\n01\n",
                capture_output=True,
                text=True,
                check=True,
            )

            values = _dotenv(workspace / ".env")
            self.assertEqual(values["TRADING_MODE"], "paper")
            self.assertEqual(values["ALLOW_LIVE_ORDERS"], "false")
            self.assertEqual(values["KIS_APP_KEY_LIVE"], "live-key")
            self.assertEqual(values["KIS_APP_SECRET_LIVE"], "live-secret")
            self.assertEqual(values["KIS_ACCOUNT_NO_LIVE"], "12345678")
            self.assertEqual(values["KIS_PRODUCT_CODE_LIVE"], "01")
            self.assertEqual((workspace / ".env").stat().st_mode & 0o777, 0o600)
            self.assertNotIn("live-key", result.stdout + result.stderr)
            self.assertNotIn("live-secret", result.stdout + result.stderr)

    def test_readonly_preparation_rejects_paper_target(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "bash",
                "scripts/restore_kis_env_interactive.sh",
                "--trading-mode",
                "paper",
                "--read-only-preparation",
            ],
            cwd=root,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --trading-mode live", result.stderr)


if __name__ == "__main__":
    unittest.main()
