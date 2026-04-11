from pathlib import Path
import tempfile
import unittest

from app.universe.watchlist import load_watchlist, parse_symbol_list


class WatchlistTests(unittest.TestCase):
    def test_parse_symbol_list(self) -> None:
        self.assertEqual(parse_symbol_list("005930, 000660 ,035420"), ["005930", "000660", "035420"])
        self.assertEqual(parse_symbol_list(""), [])

    def test_load_watchlist_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            watchlist_path = root / "watchlist.txt"
            watchlist_path.write_text("# comment\n005930\n\n000660\n", encoding="utf-8")
            symbols = load_watchlist(project_root=root, watchlist_path=watchlist_path)
            self.assertEqual(symbols, ["005930", "000660"])


if __name__ == "__main__":
    unittest.main()
