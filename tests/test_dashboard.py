import json
import os
from pathlib import Path
import threading
import unittest
import urllib.request
import uuid
from unittest.mock import patch

from app.services.dashboard import build_dashboard_snapshot, prepare_dashboard_server
from app.services.orchestrator import run_synthetic_dev_cycle


class DashboardTests(unittest.TestCase):
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

    def test_build_dashboard_snapshot_creates_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            snapshot = build_dashboard_snapshot(project_root=root, refresh_seconds=5, recent_limit=5)

        self.assertTrue(snapshot.snapshot_html_path.exists())
        self.assertTrue(snapshot.snapshot_json_path.exists())
        self.assertIn("runtime_summary", snapshot.payload)
        self.assertIn("active_model", snapshot.payload)
        html = snapshot.snapshot_html_path.read_text(encoding="utf-8")
        self.assertIn("실시간 주식 예측 운영 대시보드", html)
        self.assertIn("최근 예측", html)

    def test_dashboard_server_serves_health_and_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runtime_root, env = self._prepare_runtime_root()
        with patch.dict(os.environ, env, clear=False):
            run_synthetic_dev_cycle(project_root=root, symbol="005930", minutes=70, train_horizon_min=15)
            self._seed_dashboard_inputs(runtime_root)
            server, info = prepare_dashboard_server(
                project_root=root,
                host="127.0.0.1",
                port=0,
                refresh_seconds=3,
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
        self.assertIn("실시간 주식 예측 운영 대시보드", html)


if __name__ == "__main__":
    unittest.main()
