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
        self.assertNotIn("generate_e7_post_recovery_progress.py", section)
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

    def test_post_recovery_observation_runs_independently_once(self) -> None:
        section = _section(
            self.text, "## 3. Post-close procedure", "## 4. Phase 0 check",
        )
        command = "python3 scripts/generate_e7_post_recovery_progress.py"
        self.assertEqual(section.count(command), 1)
        self.assertIn("각 항목을 최대 1회", section)
        self.assertIn("기존 E7 명령이 실패해도", section)
        self.assertIn("자동 재시도하지 않는다", section)
        self.assertNotIn("&&", section)

    def test_post_recovery_contract_does_not_activate_official_evaluation(self) -> None:
        section = _section(self.text, "## 5. E7 check", "## 6. KIS paper")
        self.assertIn("e7-post-recovery-progress-v1", section)
        self.assertIn(
            "16a22ce5801cd1f38d21aee98bfe806fa809a3c4061d2f61e4bdb5b16b20e740",
            section,
        )
        self.assertIn("approved_contract_hash를 전달하지 않는다", section)
        self.assertIn("official_evaluation_permitted=false", section)
        self.assertIn("waiting_explicit_activation", section)
        self.assertIn("not_started", section)
        self.assertIn("not_run", section)

    def test_fresh_recheck_is_reported_without_hiding_original_failure(self) -> None:
        section = _section(self.text, "## 5. E7 check", "## 6. KIS paper")
        self.assertIn("report_path", section)
        self.assertIn("rechecks/", section)
        self.assertIn("기존 E7의 CRITICAL을 낮추지 않는다", section)
        self.assertIn("invalid_evidence", section)
        self.assertIn("generated_at", section)
        self.assertIn("ATTENTION", section)

    def test_final_report_separates_original_and_fixed_interval_evidence(self) -> None:
        section = self.text.split("## 11. Final report", 1)[1]
        self.assertIn("복구 후 고정 구간 E7 관측", section)
        self.assertIn("기존 누적 E7과 별도 줄", section)

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
