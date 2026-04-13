import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import threading
import unittest
import urllib.request
import uuid
from unittest.mock import MagicMock, patch

from app.config.settings import load_settings

from app.services.dashboard import build_dashboard_snapshot, prepare_dashboard_server
from app.services.orchestrator import run_synthetic_dev_cycle
from app.services.runtime import run_demo_pipeline
from app.services.streaming import build_sample_ws_frames, replay_ws_frames
from app.storage.contracts import MarketTickEvent, MinuteBar, Prediction
from app.storage.runtime_writer import RuntimeWriter


class DashboardTests(unittest.TestCase):
    def _mock_account_report(self) -> MagicMock:
        report = MagicMock()
        report.to_dict.return_value = {
            "ok": True,
            "trading_mode": "paper",
            "fetched_at": "2026-04-13T10:50:00+09:00",
            "cache_used": False,
            "cache_age_seconds": 0,
            "error": None,
            "source": "kis-broker",
            "account_snapshot": {
                "account_no_masked": "1234****",
                "product_code": "01",
                "cash_balance": 1000000,
                "stock_evaluation_amount": 214500,
                "total_evaluation_amount": 1214500,
                "total_purchase_amount": 210000,
                "total_profit_loss_amount": 4500,
                "total_asset_amount": 1214500,
                "positions": [
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "holding_qty": 3,
                        "current_price": 71500,
                        "evaluation_amount": 214500,
                        "evaluation_profit_loss_amount": 4500,
                    }
                ],
            },
        }
        return report

    def _prepare_runtime_root(self) -> tuple[Path, dict[str, str]]:
        root = Path(__file__).resolve().parents[1]
        runtime_root = root / ".tmp-tests" / "dashboard" / str(uuid.uuid4())
        runtime_root.mkdir(parents=True, exist_ok=True)
        env = {
            "RUNTIME_DATA_DIR": str(runtime_root),
            "DATABASE_URL": f"sqlite:///{runtime_root / 'dev.db'}",
        }
        return runtime_root, env

    def _seed_dashboard_inputs(self, runtime_root: Path) -> None:
        reports_root = runtime_root / "reports"
        (reports_root / "kis-ws").mkdir(parents=True, exist_ok=True)
        (reports_root / "codex" / "automation" / "state").mkdir(parents=True, exist_ok=True)
        (reports_root / "codex" / "automation" / "backlog").mkdir(parents=True, exist_ok=True)

        (reports_root / "kis-ws" / "latest-verification.json").write_text(
            json.dumps(
                {
                    "connection_ready": True,
                    "market_data_flow_ok": False,
                    "approval_key_issued": True,
                    "session_status": "weekend",
                    "status_note": "weekend test",
                    "frames_received": 4,
                    "control_frames": 4,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "codex" / "automation" / "state" / "latest-progress.json").write_text(
            json.dumps(
                {
                    "last_run_summary": "dashboard test progress",
                    "open_items": [{"id": "AUD-004"}],
                    "next_actions": ["check live KIS session"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_root / "codex" / "automation" / "backlog" / "latest-priority-backlog.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "AUD-004",
                            "priority": "P0",
                            "status": "open",
                            "problem": "walk-forward gate needs review",
                            "recommended_change": "tighten weakest fold gate",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _seed_actual_prediction_runtime(self, root: Path) -> None:
        settings = load_settings(project_root=root)
        writer = RuntimeWriter.from_settings(settings)
        base_time = datetime.fromisoformat("2026-04-13T10:00:00+09:00")
        future_time = base_time + timedelta(minutes=15)
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=base_time, price=70000, volume=100, source="kis-ws")
        )
        writer.write_market_tick(
            MarketTickEvent(symbol="005930", event_time=future_time, price=70700, volume=120, source="kis-ws")
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=base_time,
                open=69900,
                high=70100,
                low=69850,
                close=70000,
                volume=100,
                trade_count=5,
            )
        )
        writer.write_minute_bar(
            MinuteBar(
                symbol="005930",
                bar_time=future_time,
                open=70500,
                high=70800,
                low=70450,
                close=70700,
                volume=120,
                trade_count=6,
            )
        )
        writer.write_prediction(
            Prediction(
                prediction_id="pred-h15-online-unit-001",
                symbol="005930",
                event_time=base_time,
                horizon_min=15,
                model_version="baseline-h15-v1",
                probability_up=0.8,
                probability_flat=0.1,
                probability_down=0.1,
            )
        )

    def test_build_dashboard_snapshot_creates_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5)

        self.assertTrue(snapshot.snapshot_html_path.exists())
        self.assertTrue(snapshot.snapshot_json_path.exists())
        self.assertIn("runtime_summary", snapshot.payload)
        self.assertIn("active_model", snapshot.payload)
        self.assertTrue(snapshot.payload["dashboard_scope"]["actual_runtime_only"])
        self.assertEqual(snapshot.payload["period_filter"]["range_key"], "today")
        self.assertIn("account_views", snapshot.payload)
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("실시간 주가 예측 대시보드", html)
        self.assertIn("모의투자(가상)", html)
        self.assertIn("모의계좌(실제)", html)
        self.assertIn("실 운용계좌", html)
        self.assertIn("머신러닝 현황", html)
        self.assertIn("예측현황", html)
        self.assertIn("오늘의 리포트", html)
        self.assertIn("모의투자(가상)", html)
        self.assertIn("조회 범위", html)
        self.assertIn("기준 날짜", html)
        self.assertIn("상태 설명", html)
        self.assertIn("보유 종목", html)
        self.assertIn("매수/매도 및 체결현황", html)
        self.assertIn("최근 종료 포지션", html)
        self.assertIn("매수 주문", html)
        self.assertIn("매도 주문", html)
        self.assertIn("최근 신호", html)
        self.assertIn("localStorage.setItem", html)
        self.assertIn("운용 방식:", html)
        self.assertIn("상태 업데이트", html)
        self.assertIn("자동 새로고침: 5분", html)

    def test_dashboard_server_serves_health_and_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                server, info = prepare_dashboard_server(
                    project_root=root,
                    host="127.0.0.1",
                    port=0,
                    recent_limit=4,
                )
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    health = urllib.request.urlopen(f"{info.url}/health", timeout=5).read().decode("utf-8")
                    payload = urllib.request.urlopen(f"{info.url}/api/dashboard.json", timeout=5).read().decode("utf-8")
                    html = urllib.request.urlopen(info.url, timeout=5).read().decode("utf-8")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)

        self.assertIn('"ok": true', health.lower())
        self.assertIn('"runtime_summary"', payload)
        self.assertIn("실시간 주가 예측 대시보드", html)
        self.assertIn("모의계좌(실제)", html)
        self.assertIn('http-equiv="refresh" content="300"', html)
        self.assertIn("data-subtab-group", html)

    def test_dashboard_hides_demo_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_demo_pipeline(project_root=root, symbol="005930")
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertEqual(snapshot.payload["runtime_summary"]["predictions"], 0)
        self.assertEqual(snapshot.payload["runtime_summary"]["orders"], 0)
        self.assertIsNone(snapshot.payload["latest_portfolio_snapshot"])
        self.assertEqual(snapshot.payload["recent_predictions"], [])
        self.assertEqual(snapshot.payload["recent_orders"], [])
        self.assertEqual(snapshot.payload["learning_context"]["mode"], "offline_research")

    def test_dashboard_hides_replay_runtime_rows(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            replay_ws_frames(project_root=root, frames=build_sample_ws_frames("005930"))
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertEqual(snapshot.payload["runtime_summary"]["predictions"], 0)
        self.assertEqual(snapshot.payload["runtime_summary"]["orders"], 0)
        self.assertEqual(snapshot.payload["recent_predictions"], [])
        self.assertEqual(snapshot.payload["recent_orders"], [])

    def test_dashboard_includes_broker_account_section(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertIn("broker_account_report", snapshot.payload)
        self.assertEqual(snapshot.payload["broker_account_report"]["account_snapshot"]["account_no_masked"], "1234****")
        self.assertIn("paper_account_report", snapshot.payload)
        self.assertIn("live_account_report", snapshot.payload)
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("모의계좌(실제)", html)
        self.assertIn("실 운용계좌", html)

    def test_dashboard_prediction_view_includes_expected_and_actual_changes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            self._seed_dashboard_inputs(runtime_root)
            self._seed_actual_prediction_runtime(root)
            with patch("app.services.dashboard.refresh_kis_account_report", return_value=self._mock_account_report()):
                snapshot = build_dashboard_snapshot(project_root=root, recent_limit=5)

        recent_predictions = snapshot.payload["recent_predictions"]
        self.assertEqual(len(recent_predictions), 1)
        row = recent_predictions[0]
        self.assertEqual(row["symbol_name"], "삼성전자")
        self.assertTrue(str(row["predicted_change_text"]).startswith("상승 우세 /"))
        self.assertEqual(row["actual_change_text"], "+700원 (+1.00%)")
        self.assertEqual(row["success_text"], "성공")


if __name__ == "__main__":
    unittest.main()
