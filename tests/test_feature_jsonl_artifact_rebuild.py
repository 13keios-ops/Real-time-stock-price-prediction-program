import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.rebuild_feature_jsonl_artifacts import rebuild_feature_jsonl


class FeatureJsonlArtifactRebuildTests(unittest.TestCase):
    def _seed_database(self, database_path: Path) -> None:
        connection = sqlite3.connect(database_path)
        connection.executescript(
            """
            CREATE TABLE feature_model_inputs (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                feature_set_version TEXT NOT NULL,
                values_json TEXT NOT NULL,
                PRIMARY KEY (symbol, event_time, feature_set_version)
            );
            CREATE TABLE feature_labels (
                symbol TEXT NOT NULL,
                event_time TEXT NOT NULL,
                horizon_min INTEGER NOT NULL,
                label TEXT NOT NULL,
                threshold_pct REAL NOT NULL,
                future_return_pct REAL NOT NULL,
                PRIMARY KEY (symbol, event_time, horizon_min)
            );
            """
        )
        connection.executemany(
            "INSERT INTO feature_model_inputs VALUES (?, ?, ?, ?)",
            [
                ("005930", "2026-07-31T09:00:00+09:00", "feature-set-v1", json.dumps({"spread_bps": 11.0})),
                ("000660", "2026-07-31T09:01:00+09:00", "feature-set-v1", json.dumps({"spread_bps": 9.0})),
            ],
        )
        connection.executemany(
            "INSERT INTO feature_labels VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("005930", "2026-07-31T09:00:00+09:00", 15, "up", 0.4, 0.7),
                ("005930", "2026-07-31T09:00:00+09:00", 60, "flat", 0.4, 0.1),
            ],
        )
        connection.commit()
        connection.close()

    def test_rebuild_uses_sqlite_primary_keys_and_removes_duplicate_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime-data"
            feature_dir = runtime_dir / "feature" / "2026-07-31"
            feature_dir.mkdir(parents=True)
            database_path = runtime_dir / "dev.db"
            self._seed_database(database_path)
            (feature_dir / "model_inputs.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "005930", "event_time": "2026-07-31T09:00:00+09:00", "feature_set_version": "feature-set-v1", "values": {"spread_bps": -20000.0}}),
                        json.dumps({"symbol": "005930", "event_time": "2026-07-31T09:00:00+09:00", "feature_set_version": "feature-set-v1", "values": {"spread_bps": 999.0}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (feature_dir / "labels.jsonl").write_text(
                json.dumps({"symbol": "005930", "event_time": "2026-07-31T09:00:00+09:00", "horizon_min": 15, "label": "down", "threshold_pct": 0.4, "future_return_pct": -0.7})
                + "\n",
                encoding="utf-8",
            )

            dry_run = rebuild_feature_jsonl(
                runtime_data_dir=runtime_dir,
                database_path=database_path,
                execute=False,
                discard_backup=False,
            )
            result = rebuild_feature_jsonl(
                runtime_data_dir=runtime_dir,
                database_path=database_path,
                execute=True,
                discard_backup=True,
            )

            self.assertEqual(dry_run["status"], "dry_run")
            self.assertEqual(dry_run["source_rows"], {"model_inputs": 2, "labels": 2})
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["backup_retained"])
            self.assertTrue(result["backup_removed"])
            self.assertEqual(result["verified_rows"], {"model_inputs": 2, "labels": 2})
            model_rows = [
                json.loads(line)
                for line in (runtime_dir / "feature" / "2026-07-31" / "model_inputs.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]
            label_rows = [
                json.loads(line)
                for line in (runtime_dir / "feature" / "2026-07-31" / "labels.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]

            self.assertEqual(len(model_rows), 2)
            self.assertEqual(model_rows[1]["values"]["spread_bps"], 9.0)
            self.assertEqual(len(label_rows), 2)
            self.assertEqual({row["horizon_min"] for row in label_rows}, {15, 60})
            self.assertTrue((runtime_dir / "reports" / "storage" / "latest-feature-jsonl-rebuild.json").is_file())


if __name__ == "__main__":
    unittest.main()
