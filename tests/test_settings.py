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
        self.assertIn("2026-05-01", settings.market_calendar.holidays)
        self.assertIn("2026-05-05", settings.market_calendar.holidays)
        self.assertIn("2026-12-31", settings.market_calendar.holidays)
        self.assertEqual(settings.kis_paper_account_lifecycle.account_epoch_id, "paper-2026-09-03")
        self.assertEqual(settings.kis_paper_account_lifecycle.activated_on.isoformat(), "2026-09-03")
        self.assertEqual(settings.kis_paper_account_lifecycle.expires_on.isoformat(), "2026-12-03")
        self.assertEqual(settings.kis_paper_account_lifecycle.renewal_warning_days, 30)
        self.assertEqual(settings.kis_paper_account_lifecycle.renewal_urgent_days, 7)

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

    def test_paper_product_code_defaults_to_01_when_blank(self) -> None:
        root = Path(__file__).resolve().parents[1]

        settings = load_settings(
            project_root=root,
            env={
                "KIS_ACCOUNT_NO_PAPER": "12345678",
                "KIS_PRODUCT_CODE_PAPER": "",
            },
        )

        self.assertEqual(settings.kis_paper.account_no, "12345678")
        self.assertEqual(settings.kis_paper.product_code, "01")

    def test_account_number_can_split_product_code_from_hyphenated_text(self) -> None:
        root = Path(__file__).resolve().parents[1]

        settings = load_settings(
            project_root=root,
            env={
                "KIS_ACCOUNT_NO_PAPER": "12345678-03",
                "KIS_PRODUCT_CODE_PAPER": "",
            },
        )

        self.assertEqual(settings.kis_paper.account_no, "12345678")
        self.assertEqual(settings.kis_paper.product_code, "03")

    def test_placeholder_product_code_is_treated_as_blank_and_defaults_to_01(self) -> None:
        root = Path(__file__).resolve().parents[1]

        settings = load_settings(
            project_root=root,
            env={
                "KIS_ACCOUNT_NO_PAPER": "12345678",
                "KIS_PRODUCT_CODE_PAPER": "여기에_상품코드",
            },
        )

        self.assertEqual(settings.kis_paper.account_no, "12345678")
        self.assertEqual(settings.kis_paper.product_code, "01")


if __name__ == "__main__":
    unittest.main()
