import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_audit import GENESIS_HASH, LiveAuditLog, build_live_audit_event, verify_live_audit_chain
from app.storage.jsonl_store import JsonlArtifactStore
from app.storage.runtime_writer import RuntimeWriter
from app.storage.sqlite_store import SQLiteRuntimeStore


class LiveAuditTests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-audit" / str(uuid.uuid4())

    def _writer(self, root: Path) -> RuntimeWriter:
        return RuntimeWriter(
            jsonl_store=JsonlArtifactStore(root / "runtime-data"),
            sqlite_store=SQLiteRuntimeStore(root / "dev.db"),
        )

    def _append_fixture(self, audit: LiveAuditLog, *, event_time: datetime, event_type: str = "order_intent_created"):
        return audit.append(
            event_time=event_time,
            trading_day="2026-05-18",
            event_type=event_type,
            actor="system",
            symbol="005930",
            order_id="live-order-1",
            prediction_id="prediction-1",
            signal_id="signal-1",
            gate_decision_id="gate-1",
            rule_version="rule-1",
            model_version="model-1",
            data_snapshot_id="snapshot-1",
            detail_json={"reason": "fixture", "source": "unit_test", "gate_decision": {"allowed": True}},
        )

    def test_append_builds_hash_chain_and_writes_jsonl_and_sqlite(self) -> None:
        root = self._root()
        writer = self._writer(root)
        audit = LiveAuditLog(writer)
        now = datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc)

        first = self._append_fixture(audit, event_time=now)
        second = self._append_fixture(audit, event_time=now + timedelta(seconds=1), event_type="order_guard_passed")

        self.assertEqual(first.previous_hash, GENESIS_HASH)
        self.assertEqual(second.previous_hash, first.event_hash)
        self.assertEqual(writer.sqlite_store.count_rows("ops_live_audit_events"), 2)
        self.assertTrue((root / "runtime-data" / "ops" / "2026-05-18" / "live_audit_events.jsonl").exists())

        verification = audit.verify(trading_day="2026-05-18")
        self.assertTrue(verification.ok)
        self.assertEqual(verification.checked_count, 2)
        self.assertEqual(verification.latest_hash, second.event_hash)

    def test_verify_detects_payload_tamper(self) -> None:
        root = self._root()
        writer = self._writer(root)
        audit = LiveAuditLog(writer)
        event = self._append_fixture(audit, event_time=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc))
        tampered = event.to_record()
        tampered["rule_version"] = "tampered-rule"

        verification = verify_live_audit_chain([tampered])

        self.assertFalse(verification.ok)
        self.assertEqual(verification.issues[0].code, "event_hash_mismatch")

    def test_verify_detects_previous_hash_gap(self) -> None:
        root = self._root()
        writer = self._writer(root)
        audit = LiveAuditLog(writer)
        now = datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc)
        first = self._append_fixture(audit, event_time=now)
        second = self._append_fixture(audit, event_time=now + timedelta(seconds=1), event_type="order_submitted")
        broken = second.to_record()
        broken["previous_hash"] = GENESIS_HASH

        verification = verify_live_audit_chain([first, broken])

        self.assertFalse(verification.ok)
        self.assertEqual(verification.issues[0].code, "previous_hash_mismatch")

    def test_append_requires_sqlite_for_previous_hash_lookup(self) -> None:
        audit = LiveAuditLog(RuntimeWriter(jsonl_store=JsonlArtifactStore(self._root() / "runtime-data"), sqlite_store=None))

        with self.assertRaises(ValueError):
            self._append_fixture(audit, event_time=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc))

    def test_build_rejects_missing_traceability_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "prediction_id"):
            build_live_audit_event(
                event_time=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc),
                trading_day="2026-05-18",
                event_type="order_intent_created",
                actor="system",
                symbol="005930",
                order_id="live-order-1",
                prediction_id="",
                signal_id="signal-1",
                gate_decision_id="gate-1",
                rule_version="rule-1",
                model_version="model-1",
                data_snapshot_id="snapshot-1",
                previous_hash=GENESIS_HASH,
                detail_json={"source": "unit_test"},
            )

    def test_build_rejects_invalid_previous_hash(self) -> None:
        with self.assertRaisesRegex(ValueError, "previous_hash"):
            build_live_audit_event(
                event_time=datetime(2026, 5, 18, 9, 30, tzinfo=timezone.utc),
                trading_day="2026-05-18",
                event_type="order_intent_created",
                actor="system",
                symbol="005930",
                order_id="live-order-1",
                prediction_id="prediction-1",
                signal_id="signal-1",
                gate_decision_id="gate-1",
                rule_version="rule-1",
                model_version="model-1",
                data_snapshot_id="snapshot-1",
                previous_hash="not-a-hash",
                detail_json={"source": "unit_test"},
            )


if __name__ == "__main__":
    unittest.main()
