from pathlib import Path
import shutil
import unittest
import uuid

from app.config.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_defaults(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = load_settings(project_root=root, env={})

        self.assertEqual(settings.trading_mode, "paper")
        self.assertFalse(settings.allow_live_orders)
        self.assertEqual(settings.strategy.max_open_positions, 5)
        self.assertEqual(settings.market_calendar.new_entry_start, "09:15")

    def test_live_orders_require_live_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            load_settings(
                project_root=root,
                env={
                    "TRADING_MODE": "paper",
                    "ALLOW_LIVE_ORDERS": "true",
                },
            )

    def test_load_settings_reads_dotenv_when_env_not_explicitly_provided(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".tmp-tests" / "settings-dotenv" / str(uuid.uuid4())
        shutil.copytree(root / "config", temp_root / "config")
        (temp_root / ".env").write_text(
            "\n".join(
                [
                    "TRADING_MODE=paper",
                    "KIS_APP_KEY_PAPER=test-paper-key",
                    "KIS_APP_SECRET_PAPER=test-paper-secret",
                    "DATABASE_URL=sqlite:///runtime-data/dotenv.db",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        settings = load_settings(project_root=temp_root)

        self.assertEqual(settings.kis_paper.app_key, "test-paper-key")
        self.assertEqual(settings.kis_paper.app_secret, "test-paper-secret")
        self.assertTrue(str(settings.database_url).endswith("dotenv.db"))


if __name__ == "__main__":
    unittest.main()
