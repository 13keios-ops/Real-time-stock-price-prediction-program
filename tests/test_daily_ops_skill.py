import unittest
from pathlib import Path


SKILL_PATH = (
    Path(__file__).resolve().parents[1]
    / ".agents/skills/daily-ops-check/SKILL.md"
)


def _section(text: str, heading: str, next_heading: str) -> str:
    return text.split(heading, 1)[1].split(next_heading, 1)[0]


class DailyOpsSkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL_PATH.read_text(encoding="utf-8")

    def test_pre_open_does_not_run_post_close_jobs(self) -> None:
        section = _section(
            self.text,
            "## 2. Pre-open procedure",
            "## 3. Post-close procedure",
        )
        self.assertIn("run_phase1b_readonly_observation.sh", section)
        self.assertNotIn("summarize_kis_live_data_quality.py", section)
        self.assertNotIn("generate_e7_daily_evidence.sh", section)
        self.assertNotIn("recheck_paper_kis_mismatch.sh", section)

    def test_post_close_write_jobs_are_protected(self) -> None:
        section = _section(
            self.text,
            "## 3. Post-close procedure",
            "## 4. Phase 0 check",
        )
        self.assertIn("protected post-close no write", section)
        self.assertIn("live runtime 정지", section)
        self.assertIn("generate_e7_daily_evidence.sh", section)

    def test_phase0_same_day_duplicate_is_forbidden(self) -> None:
        section = _section(
            self.text,
            "## 4. Phase 0 check",
            "## 5. E7 check",
        )
        self.assertIn("eligible_for_phase0_gate=true", section)
        self.assertIn("중복 호출하지 않는다", section)
        self.assertIn("no-submission day", section)

    def test_missing_e7_artifact_is_not_strategy_failure(self) -> None:
        self.assertIn(
            "E7 artifact가 생성되지 않았다는 사실은 전략 실패가 아니다",
            self.text,
        )
        self.assertIn("collecting_future_sample", self.text)

    def test_collection_and_connection_are_classified_separately(self) -> None:
        self.assertIn(
            "reconnect > 0이어도 storm=0, coverage>=95%, lineage=100%",
            self.text,
        )
        self.assertIn("collection ok / connection watch", self.text)

    def test_historical_one_offs_are_not_rerun(self) -> None:
        self.assertIn("E1/E5는 자동 재실행하지 않는다", self.text)
        self.assertIn(
            "E1/E5와 과거 Phase 0 recovery를 자동 재실행하지 않는다",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
