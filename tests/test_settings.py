from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
