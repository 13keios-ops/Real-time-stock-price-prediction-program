from pathlib import Path
import re
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LiveClientIsolationTests(unittest.TestCase):
    def test_live_readonly_paths_do_not_bypass_wrapper(self) -> None:
        allowed_paths = {
            Path("app/brokers/kis_readonly.py"),
            Path("app/services/broker_paper.py"),
        }
        direct_constructor_pattern = re.compile(r"\bKisRestQuoteClient\s*\(")
        matches: set[Path] = set()

        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            relative_path = path.relative_to(PROJECT_ROOT)
            if direct_constructor_pattern.search(path.read_text(encoding="utf-8")):
                matches.add(relative_path)

        self.assertEqual(matches, allowed_paths)

    def test_query_only_kis_paths_use_readonly_factory(self) -> None:
        query_only_paths = {
            Path("app/__main__.py"),
            Path("app/collectors/historical.py"),
            Path("app/services/collector.py"),
            Path("app/services/kis_account.py"),
            Path("app/services/runtime.py"),
        }

        for relative_path in query_only_paths:
            with self.subTest(path=str(relative_path)):
                source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("get_kis_readonly_client", source)
                self.assertNotRegex(source, r"\bKisRestQuoteClient\s*\(")

    def test_paper_mirroring_still_uses_paper_profile(self) -> None:
        broker_paper_source = (PROJECT_ROOT / "app" / "services" / "broker_paper.py").read_text(encoding="utf-8")

        self.assertIn('get_kis_profile(settings, "paper")', broker_paper_source)
        self.assertIn("submit_cash_order", broker_paper_source)
        self.assertNotIn("get_kis_live_readonly_client", broker_paper_source)

    def test_order_submit_cancel_surface_stays_in_broker_or_order_manager_boundaries(self) -> None:
        allowed_paths = {
            Path("app/brokers/kis_live_order.py"),
            Path("app/brokers/kis_quote_rest.py"),
            Path("app/services/broker_paper.py"),
            Path("app/services/live_order_manager.py"),
        }
        order_surface_pattern = re.compile(r"\b(submit_cash_order|cancel_order)\s*\(")
        matches: set[Path] = set()

        for path in (PROJECT_ROOT / "app").rglob("*.py"):
            relative_path = path.relative_to(PROJECT_ROOT)
            if order_surface_pattern.search(path.read_text(encoding="utf-8")):
                matches.add(relative_path)

        self.assertEqual(matches, allowed_paths)


if __name__ == "__main__":
    unittest.main()
