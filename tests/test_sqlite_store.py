from pathlib import Path
import uuid
import unittest
from unittest.mock import patch

from app.storage.sqlite_store import SQLiteRuntimeStore


class SQLiteRuntimeStoreTests(unittest.TestCase):
    def test_initialize_schema_can_be_skipped(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        with patch.object(SQLiteRuntimeStore, "_initialize_schema") as mocked_initialize:
            SQLiteRuntimeStore(database_path, initialize_schema=False)

        mocked_initialize.assert_not_called()

    def test_initialize_schema_runs_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database_path = root / ".tmp-tests" / "sqlite-store" / str(uuid.uuid4()) / "dev.db"

        with patch.object(SQLiteRuntimeStore, "_initialize_schema") as mocked_initialize:
            SQLiteRuntimeStore(database_path)

        mocked_initialize.assert_called_once()


if __name__ == "__main__":
    unittest.main()
