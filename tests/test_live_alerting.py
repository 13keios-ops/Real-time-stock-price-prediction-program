import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_alerting import (
    LiveAlert,
    LiveAlertOutbox,
    build_live_monitoring_alerts,
    render_email_alert,
    render_telegram_alert,
    route_live_alert,
)


class LiveAlertingTests(unittest.TestCase):
    def _now(self) -> datetime:
        return datetime(2026, 5, 18, 0, 30, tzinfo=timezone.utc)

    def _root(self) -> Path:
        return Path(__file__).resolve().parents[1] / ".tmp-tests" / "live-alerting" / str(uuid.uuid4())

    def _alert(self, *, severity: str, event_type: str = "market_status_stale") -> LiveAlert:
        return LiveAlert(
            alert_id=f"alert-{severity}-{event_type}",
            created_at=self._now(),
            severity=severity,
            event_type=event_type,
            title="상태 확인",
            message="상태 확인이 필요합니다.",
            source="unit_test",
            trading_day="2026-05-18",
            detail_json={},
        )

    def test_route_live_alert_sends_warning_to_telegram_only(self) -> None:
        route = route_live_alert(self._alert(severity="warning"))

        self.assertEqual(route.channels, ("local", "telegram"))
        self.assertTrue(route.telegram)
        self.assertFalse(route.email)

    def test_route_live_alert_sends_critical_to_telegram_and_email(self) -> None:
        route = route_live_alert(self._alert(severity="critical", event_type="live_order_attention"))

        self.assertEqual(route.channels, ("local", "telegram", "email"))
        self.assertTrue(route.important)

    def test_route_live_alert_sends_important_warning_to_email(self) -> None:
        route = route_live_alert(self._alert(severity="warning", event_type="live_runtime_down"))

        self.assertEqual(route.channels, ("local", "telegram", "email"))
        self.assertTrue(route.important)

    def test_build_live_monitoring_alerts_marks_mismatch_and_attention_critical(self) -> None:
        alerts = build_live_monitoring_alerts(
            created_at=self._now(),
            live_fill_consistency={
                "trading_day": "2026-05-18",
                "mismatch_count": 1,
                "mismatches": [{"order_id": "order-1"}],
            },
            live_order_attention={
                "trading_day": "2026-05-18",
                "attention_count": 2,
                "attention_orders": [{"order_id": "order-2"}],
            },
        )

        self.assertEqual([alert.event_type for alert in alerts], ["live_fill_mismatch", "live_order_attention"])
        self.assertTrue(all(alert.severity == "critical" for alert in alerts))
        self.assertTrue(all(route_live_alert(alert).email for alert in alerts))

    def test_build_live_monitoring_alerts_uses_state_fingerprint_for_alert_id(self) -> None:
        payload = {
            "trading_day": "2026-05-18",
            "mismatch_count": 1,
            "mismatches": [{"order_id": "order-1"}],
        }

        first = build_live_monitoring_alerts(
            created_at=self._now(),
            live_fill_consistency=payload,
            live_order_attention=None,
        )
        second = build_live_monitoring_alerts(
            created_at=self._now() + timedelta(minutes=5),
            live_fill_consistency=payload,
            live_order_attention=None,
        )

        self.assertEqual(first[0].alert_id, second[0].alert_id)

    def test_build_live_monitoring_alerts_can_grace_new_attention_state(self) -> None:
        alerts = build_live_monitoring_alerts(
            created_at=self._now(),
            live_fill_consistency=None,
            live_order_attention={
                "trading_day": "2026-05-18",
                "attention_count": 1,
                "max_attention_age_minutes": 0.5,
                "attention_grace_minutes": 1.0,
                "attention_orders": [{"order_id": "order-1"}],
            },
        )

        self.assertEqual(alerts, ())

    def test_build_live_monitoring_alerts_emits_after_grace_window(self) -> None:
        alerts = build_live_monitoring_alerts(
            created_at=self._now(),
            live_fill_consistency=None,
            live_order_attention={
                "trading_day": "2026-05-18",
                "attention_count": 1,
                "max_attention_age_minutes": 2.0,
                "attention_grace_minutes": 1.0,
                "attention_orders": [{"order_id": "order-1"}],
            },
        )

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].event_type, "live_order_attention")

    def test_outbox_writes_local_telegram_and_email_records_without_sending(self) -> None:
        alert = self._alert(severity="critical", event_type="live_fill_mismatch")
        outbox = LiveAlertOutbox(self._root())

        route = outbox.write_alert(alert)

        self.assertEqual(route.channels, ("local", "telegram", "email"))
        for channel in route.channels:
            path = outbox.alerts_root / channel / f"alerts-{self._now().date().isoformat()}.jsonl"
            self.assertTrue(path.exists())
            record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["channel"], channel)
            self.assertEqual(record["delivery_mode"], "outbox_only")
            self.assertEqual(record["alert"]["alert_id"], alert.alert_id)

    def test_outbox_suppresses_duplicate_alert_id_per_channel(self) -> None:
        alert = self._alert(severity="critical", event_type="live_fill_mismatch")
        outbox = LiveAlertOutbox(self._root())

        first = outbox.write_alert(alert)
        second = outbox.write_alert(alert)

        self.assertEqual(first.written_channels, ("local", "telegram", "email"))
        self.assertEqual(second.written_channels, ())
        self.assertEqual(second.suppressed_channels, ("local", "telegram", "email"))
        for channel in first.channels:
            path = outbox.alerts_root / channel / f"alerts-{self._now().date().isoformat()}.jsonl"
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_outbox_redacts_sensitive_detail_json_before_write(self) -> None:
        alert = LiveAlert(
            alert_id="alert-redaction",
            created_at=self._now(),
            severity="critical",
            event_type="broker_account_mismatch",
            title="계좌 정합성 확인",
            message="계좌 snapshot 확인이 필요합니다.",
            source="unit_test",
            trading_day="2026-05-18",
            detail_json={
                "raw_response": {
                    "account_number": "1234567890",
                    "app_secret": "secret-value",
                    "pdno": "005930",
                }
            },
        )
        outbox = LiveAlertOutbox(self._root())

        outbox.write_alert(alert)

        path = outbox.alerts_root / "local" / f"alerts-{self._now().date().isoformat()}.jsonl"
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        raw_response = record["alert"]["detail_json"]["raw_response"]
        self.assertEqual(raw_response["account_number"], "<REDACTED>")
        self.assertEqual(raw_response["app_secret"], "<REDACTED>")
        self.assertEqual(raw_response["pdno"], "005930")

    def test_renderers_do_not_require_secret_values(self) -> None:
        alert = self._alert(severity="critical", event_type="kill_switch_enabled")

        telegram_text = render_telegram_alert(alert)
        email = render_email_alert(alert)

        self.assertIn("상태 확인", telegram_text)
        self.assertIn("LIVE CRITICAL", email["subject"])
        self.assertIn("상태 확인이 필요합니다.", email["body"])


if __name__ == "__main__":
    unittest.main()
