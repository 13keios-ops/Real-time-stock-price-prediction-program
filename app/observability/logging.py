"""Logging helpers for local runtime execution."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config.settings import AppSettings


def ensure_runtime_directories(settings: AppSettings) -> dict[str, Path]:
    runtime_root = settings.runtime_data_dir
    directories = {
        "runtime_root": runtime_root,
        "app_logs": runtime_root / "logs" / "app",
        "reports": settings.codex_review.report_dir,
        "raw_trading": runtime_root / "trading",
        "ml": runtime_root / "ml",
        "cache": runtime_root / "cache",
    }
    for path in directories.values():
        path.mkdir(parents=True, exist_ok=True)
    return directories


def configure_logging(settings: AppSettings) -> Path:
    directories = ensure_runtime_directories(settings)
    log_file = directories["app_logs"] / "app.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    logging.getLogger(__name__).info("Runtime logging initialized at %s", log_file)
    return log_file
