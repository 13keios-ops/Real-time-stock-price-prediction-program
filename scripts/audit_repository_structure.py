#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRECTORIES = (
    "app/brokers",
    "app/collectors",
    "app/features",
    "app/labels",
    "app/models",
    "app/services",
    "app/paper_trading",
    "app/portfolio",
    "app/reconciliation",
    "app/risk",
    "app/storage",
    "config",
    "docs",
    "migrations",
    "scripts",
    "tests",
)

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "WORKFLOW.md",
    "COWORK_GUIDE.md",
    "VERSION",
    "pyproject.toml",
    "docs/STATUS.md",
    "docs/SPRINT_CURRENT.md",
    "docs/logbook.md",
    "docs/Current-Implementation.md",
    "docs/Execution-Plan.md",
    "docs/Production-Transition-Progress.md",
    "docs/Repository-Structure.md",
)

ACTIVE_DOC_LINE_LIMITS = {
    "WORKFLOW.md": 250,
    "COWORK_GUIDE.md": 250,
    "docs/STATUS.md": 200,
    "docs/SPRINT_CURRENT.md": 200,
    "docs/logbook.md": 300,
    "docs/Production-Transition-Progress.md": 300,
}

HISTORICAL_MARKDOWN_PREFIXES = (
    "docs/archive/",
    "docs/cowork-reports/",
    "docs/logbook_archive/",
)

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _issue(code: str, path: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "path": path, "message": message}
    payload.update(details)
    return payload


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as handle:
        return sum(1 for _ in handle)


def _iter_current_markdown(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith((".git/", "runtime-data/", ".tmp-tests/")):
            continue
        if relative.startswith(HISTORICAL_MARKDOWN_PREFIXES):
            continue
        yield path


def _extract_link_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(maxsplit=1)[0] if value else ""


def _inspect_markdown(root: Path, path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    relative = path.relative_to(root).as_posix()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    visible_lines: list[tuple[int, str]] = []
    active_fence: str | None = None

    for number, line in enumerate(lines, 1):
        fence = FENCE_RE.match(line)
        if fence:
            token = fence.group(1)
            if active_fence is None:
                active_fence = token
            elif active_fence == token:
                active_fence = None
            continue
        if active_fence is None:
            visible_lines.append((number, line))

    if active_fence is not None:
        errors.append(_issue("unclosed_code_fence", relative, "Markdown code fence is not closed."))

    h1_count = sum(1 for _, line in visible_lines if line.startswith("# "))
    if h1_count != 1:
        errors.append(
            _issue(
                "invalid_h1_count",
                relative,
                "Current Markdown must contain exactly one top-level heading.",
                h1_count=h1_count,
            )
        )

    for number, line in visible_lines:
        for match in MARKDOWN_LINK_RE.finditer(line):
            raw_target = _extract_link_target(match.group(1))
            if not raw_target or raw_target.startswith(("#", "http://", "https://", "mailto:", "data:")):
                continue
            target = unquote(raw_target.split("#", 1)[0])
            if not target:
                continue
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = (path.parent / candidate).resolve()
            if not candidate.exists():
                errors.append(
                    _issue(
                        "broken_local_markdown_link",
                        relative,
                        "Local Markdown link target does not exist.",
                        line=number,
                        target=raw_target,
                    )
                )

    limit = ACTIVE_DOC_LINE_LIMITS.get(relative)
    if limit is not None and len(lines) > limit:
        warnings.append(
            _issue(
                "active_document_too_large",
                relative,
                "Active status document should be compacted or archived.",
                lines=len(lines),
                limit=limit,
            )
        )

    return errors, warnings


def audit_repository(root: Path) -> dict[str, Any]:
    root = root.resolve()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for relative in REQUIRED_DIRECTORIES:
        path = root / relative
        if not path.is_dir():
            errors.append(_issue("missing_required_directory", relative, "Required directory is missing."))

    for relative in REQUIRED_FILES:
        path = root / relative
        if not path.is_file():
            errors.append(_issue("missing_required_file", relative, "Required file is missing."))

    markdown_files = list(_iter_current_markdown(root))
    for path in markdown_files:
        doc_errors, doc_warnings = _inspect_markdown(root, path)
        errors.extend(doc_errors)
        warnings.extend(doc_warnings)

    for pattern in ("*.orig", "*.rej"):
        for path in sorted(root.rglob(pattern)):
            relative = path.relative_to(root).as_posix()
            if relative.startswith((".git/", "runtime-data/", ".tmp-tests/")):
                continue
            errors.append(_issue("patch_artifact_present", relative, "Patch backup/reject artifact is present."))

    pytest_cache = root / ".pytest_cache"
    if pytest_cache.exists():
        warnings.append(
            _issue(
                "root_pytest_cache_present",
                ".pytest_cache",
                "Generated pytest cache is present at repository root.",
            )
        )

    python_files = sorted((root / "app").rglob("*.py")) if (root / "app").is_dir() else []
    for path in python_files:
        lines = _line_count(path)
        if lines > 5000:
            warnings.append(
                _issue(
                    "large_python_module",
                    path.relative_to(root).as_posix(),
                    "Large module should be reduced only through a separately tested refactor.",
                    lines=lines,
                    threshold=5000,
                )
            )

    return {
        "ok": not errors,
        "root": str(root),
        "summary": {
            "errors": len(errors),
            "warnings": len(warnings),
            "current_markdown_files": len(markdown_files),
            "python_files": len(python_files),
        },
        "errors": errors,
        "warnings": warnings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit repository structure and current Markdown documents.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit_repository(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
