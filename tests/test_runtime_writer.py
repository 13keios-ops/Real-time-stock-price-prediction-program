from pathlib import Path
import unittest
from unittest.mock import patch

from app.config.settings import load_settings
from app.storage.runtime_writer import RuntimeWriter


class RuntimeWriterTests(unittest.TestCase):
    def test_from_settings_passes_custom_sqlite_retry_options(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        settings = load_settings(project_root=project_root)

        with patch("app.storage.runtime_writer.SQLiteRuntimeStore") as mocked_store:
            RuntimeWriter.from_settings(
                settings,
                sqlite_busy_timeout_ms=30_000,
                sqlite_read_retry_delays=(0.0, 0.05),
                sqlite_write_retry_delays=(0.0, 0.5, 1.0),
            )

        mocked_store.assert_called_once()
        _, kwargs = mocked_store.call_args
        self.assertEqual(kwargs["busy_timeout_ms"], 30_000)
        self.assertEqual(kwargs["read_retry_delays"], (0.0, 0.05))
        self.assertEqual(kwargs["write_retry_delays"], (0.0, 0.5, 1.0))


if __name__ == "__main__":
    unittest.main()
