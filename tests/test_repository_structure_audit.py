from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.audit_repository_structure import (
    ACTIVE_DOC_LINE_LIMITS,
    REPO_ROOT,
    REQUIRED_DIRECTORIES,
    REQUIRED_FILES,
    audit_repository,
)


class RepositoryStructureAuditTests(unittest.TestCase):
    def _build_minimum_repository(self, root: Path) -> None:
        for relative in REQUIRED_DIRECTORIES:
            (root / relative).mkdir(parents=True, exist_ok=True)

        for relative in REQUIRED_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix == ".md":
                path.write_text(f"# {path.stem}\n", encoding="utf-8")
            else:
                path.write_text("test\n", encoding="utf-8")

    def _temporary_root(self) -> tempfile.TemporaryDirectory[str]:
        temp_root = REPO_ROOT / ".tmp-tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=temp_root)

    def test_minimum_repository_passes(self) -> None:
        with self._temporary_root() as temp:
            root = Path(temp)
            self._build_minimum_repository(root)
            status_path = root / "docs/STATUS.md"
            status_path.write_text("# Status\n\n[README](../README.md)\n", encoding="utf-8")

            report = audit_repository(root)

        self.assertTrue(report["ok"])
        self.assertEqual(report["errors"], [])

    def test_broken_link_and_patch_artifact_are_errors(self) -> None:
        with self._temporary_root() as temp:
            root = Path(temp)
            self._build_minimum_repository(root)
            status_path = root / "docs/STATUS.md"
            status_path.write_text("# Status\n\n[missing](missing.md)\n", encoding="utf-8")
            (root / "bad.rej").write_text("reject\n", encoding="utf-8")

            report = audit_repository(root)

        codes = {item["code"] for item in report["errors"]}
        self.assertFalse(report["ok"])
        self.assertIn("broken_local_markdown_link", codes)
        self.assertIn("patch_artifact_present", codes)

    def test_fenced_heading_is_ignored_and_large_status_is_warning(self) -> None:
        with self._temporary_root() as temp:
            root = Path(temp)
            self._build_minimum_repository(root)
            (root / "README.md").write_text(
                "# README\n\n```bash\n# not a heading\n```\n",
                encoding="utf-8",
            )
            limit = ACTIVE_DOC_LINE_LIMITS["docs/STATUS.md"]
            (root / "docs/STATUS.md").write_text(
                "# Status\n" + "line\n" * limit,
                encoding="utf-8",
            )

            report = audit_repository(root)

        warning_codes = {item["code"] for item in report["warnings"]}
        error_codes = {item["code"] for item in report["errors"]}
        self.assertTrue(report["ok"])
        self.assertIn("active_document_too_large", warning_codes)
        self.assertNotIn("invalid_h1_count", error_codes)


if __name__ == "__main__":
    unittest.main()
