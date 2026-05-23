import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.live_kill_switch import LiveKillSwitch


class LiveKillSwitchTests(unittest.TestCase):
    def _path(self) -> Path:
        root = Path(__file__).resolve().parents[1]
        return root / ".tmp-tests" / "live-kill-switch" / str(uuid.uuid4()) / "kill-switch.json"

    def _now(self) -> datetime:
        return datetime(2026, 5, 15, 15, 45, tzinfo=timezone.utc)

    def test_missing_state_fails_closed_but_allows_cancel_only(self) -> None:
        switch = LiveKillSwitch(self._path())

        state = switch.read_state(now=self._now())

        self.assertEqual(state.status, "missing")
        self.assertTrue(state.blocks_submit)
        self.assertEqual(state.submit_blocking_reason, "kill_switch_state_missing")
        self.assertTrue(switch.allow_cancel_only(state))

    def test_write_and_read_round_trip(self) -> None:
        switch = LiveKillSwitch(self._path())

        written = switch.write_state(
            enabled=False,
            reason="post_close_ready",
            actor="system",
            now=self._now(),
            stale_after=self._now() + timedelta(hours=2),
        )
        read_back = switch.read_state(now=self._now())

        self.assertEqual(written.status, "ok")
        self.assertEqual(read_back.status, "ok")
        self.assertFalse(read_back.enabled)
        self.assertFalse(read_back.blocks_submit)
        self.assertEqual(read_back.actor, "system")

    def test_enabled_state_blocks_submit(self) -> None:
        switch = LiveKillSwitch(self._path())

        state = switch.write_state(
            enabled=True,
            reason="manual_stop",
            actor="account_owner",
            now=self._now(),
            stale_after=self._now() + timedelta(hours=1),
        )

        self.assertTrue(state.blocks_submit)
        self.assertEqual(state.submit_blocking_reason, "kill_switch_enabled")

    def test_broken_and_stale_states_fail_closed(self) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        switch = LiveKillSwitch(path)

        broken = switch.read_state(now=self._now())
        self.assertEqual(broken.status, "broken")
        self.assertTrue(broken.blocks_submit)

        path.write_text(
            json.dumps(
                {
                    "enabled": False,
                    "reason": "old_state",
                    "actor": "system",
                    "scope": "global",
                    "symbol": None,
                    "updated_at": (self._now() - timedelta(hours=2)).isoformat(),
                    "stale_after": (self._now() - timedelta(hours=1)).isoformat(),
                }
            ),
            encoding="utf-8",
        )
        stale = switch.read_state(now=self._now())
        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.submit_blocking_reason, "kill_switch_state_stale")

    def test_codex_actor_is_rejected(self) -> None:
        switch = LiveKillSwitch(self._path())

        with self.assertRaises(ValueError):
            switch.write_state(
                enabled=False,
                reason="fixture",
                actor="codex",
                now=self._now(),
                stale_after=self._now() + timedelta(hours=1),
            )


if __name__ == "__main__":
    unittest.main()
