import json
import sqlite3
import subprocess
import unittest
import uuid
from pathlib import Path


class KisPaperFixtureExportScriptTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def _work_dir(self) -> Path:
        return self._root() / ".tmp-tests" / "kis-paper-fixture-export" / str(uuid.uuid4())

    def _database(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                CREATE TABLE broker_paper_order_submissions (
                    submission_id TEXT,
                    event_time TEXT,
                    detail_json TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE broker_paper_order_status_snapshots (
                    sync_id TEXT,
                    synced_at TEXT,
                    detail_json TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO broker_paper_order_submissions
                VALUES (?, ?, ?)
                """,
                (
                    "sub-1",
                    "2026-05-17T09:00:00+09:00",
                    json.dumps(
                        {
                            "authorization": "Bearer token",
                            "raw_output": {"ODNO": "order-1", "ORD_TMD": "090000"},
                        }
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO broker_paper_order_status_snapshots
                VALUES (?, ?, ?)
                """,
                (
                    "sync-1",
                    "2026-05-17T09:01:00+09:00",
                    json.dumps(
                        {
                            "pdno": "005930",
                            "ctac_tlno": "01012345678",
                            "inqr_ip_addr": "192.0.2.10",
                            "ordr_empno": "employee-1",
                            "rmn_qty": "1",
                        }
                    ),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return path

    def test_exports_redacted_candidates_from_read_only_database(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        db_path = self._database(work_dir / "dev.db")
        output_path = work_dir / "candidate.json"

        result = subprocess.run(
            [
                "python",
                "scripts/export_kis_paper_fixture_candidates.py",
                "--database-path",
                str(db_path),
                "--output-path",
                str(output_path),
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )

        summary = json.loads(result.stdout)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        submission = payload["tables"]["broker_paper_order_submissions"]["latest_candidate"]["redacted_detail_json"]
        status = payload["tables"]["broker_paper_order_status_snapshots"]["latest_candidate"]["redacted_detail_json"]
        self.assertEqual(summary["status"], "ok")
        self.assertTrue(summary["redaction_ok"])
        self.assertTrue(payload["tables"]["broker_paper_order_submissions"]["latest_candidate"]["redaction_ok"])
        self.assertTrue(payload["tables"]["broker_paper_order_status_snapshots"]["latest_candidate"]["redaction_ok"])
        self.assertEqual(submission["authorization"], "<REDACTED>")
        self.assertEqual(submission["raw_output"]["ODNO"], "order-1")
        self.assertEqual(status["pdno"], "005930")
        self.assertEqual(status["ctac_tlno"], "<REDACTED>")
        self.assertEqual(status["inqr_ip_addr"], "<REDACTED>")
        self.assertEqual(status["ordr_empno"], "<REDACTED>")

    def test_output_path_must_stay_inside_repository(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        db_path = self._database(work_dir / "dev.db")

        result = subprocess.run(
            [
                "python",
                "scripts/export_kis_paper_fixture_candidates.py",
                "--database-path",
                str(db_path),
                "--output-path",
                "/tmp/kis-paper-fixture-candidate.json",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output_path must stay inside repository root", result.stderr)

    def test_fail_on_redaction_findings_allows_clean_export(self) -> None:
        root = self._root()
        work_dir = self._work_dir()
        db_path = self._database(work_dir / "dev.db")
        output_path = work_dir / "candidate.json"

        result = subprocess.run(
            [
                "python",
                "scripts/export_kis_paper_fixture_candidates.py",
                "--database-path",
                str(db_path),
                "--output-path",
                str(output_path),
                "--fail-on-redaction-findings",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(payload["redaction_ok"])


if __name__ == "__main__":
    unittest.main()
