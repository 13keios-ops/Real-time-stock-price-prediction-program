"""Application settings loader for the project foundation."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.utils.time import parse_hhmm


@dataclass(slots=True)
class KisCredentialSet:
    app_key: str
    app_secret: str
    account_no: str
    product_code: str


@dataclass(slots=True)
class KisEnvironmentSettings:
    hts_id: str
    customer_type: str
    rest_url_live: str
    rest_url_paper: str
    ws_url_live: str
    ws_url_paper: str


@dataclass(slots=True)
class StrategySettings:
    strategy_version: str
    portfolio_version: str
    label_threshold_15: float
    label_threshold_60: float
    min_signal_confidence: float
    max_position_pct: float
    max_open_positions: int
    slippage_bps: float
    max_spread_bps: float
    enable_paper_execution: bool


@dataclass(slots=True)
class MarketCalendarSettings:
    timezone: str
    session_open: str
    new_entry_start: str
    new_entry_end: str
    forced_flat_time: str
    session_close: str


@dataclass(slots=True)
class CodexReviewSettings:
    enabled: bool
    report_dir: Path
    scope: str


@dataclass(slots=True)
class AppSettings:
    project_root: Path
    app_name: str
    app_env: str
    timezone: str
    runtime_data_dir: Path
    artifact_store: str
    database_url: str
    trading_mode: str
    allow_live_orders: bool
    kis_paper: KisCredentialSet
    kis_live: KisCredentialSet
    kis_environment: KisEnvironmentSettings
    feature_set_version: str
    model_version_h15: str
    model_version_h60: str
    universe_selection_rule: str
    strategy: StrategySettings
    market_calendar: MarketCalendarSettings
    codex_review: CodexReviewSettings


def _read_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    env_map: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_map[key.strip()] = value.strip().strip('"').strip("'")
    return env_map


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(env: dict[str, str], key: str, default: float) -> float:
    value = env.get(key)
    return float(value) if value is not None else default


def _env_int(env: dict[str, str], key: str, default: int) -> int:
    value = env.get(key)
    return int(value) if value is not None else default


def _env_path(project_root: Path, env: dict[str, str], key: str, default: str) -> Path:
    raw = env.get(key, default)
    path = Path(raw)
    if path.is_absolute():
        return path
    return project_root / path


def _build_kis_credential_set(env: dict[str, str], prefix: str) -> KisCredentialSet:
    return KisCredentialSet(
        app_key=env.get(f"KIS_APP_KEY_{prefix}", ""),
        app_secret=env.get(f"KIS_APP_SECRET_{prefix}", ""),
        account_no=env.get(f"KIS_ACCOUNT_NO_{prefix}", ""),
        product_code=env.get(f"KIS_PRODUCT_CODE_{prefix}", ""),
    )


def load_settings(project_root: Path | None = None, env: dict[str, str] | None = None) -> AppSettings:
    """Load settings from config TOML files plus environment overrides."""

    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    if env is None:
        env_map = _read_dotenv(root / ".env")
        env_map.update(os.environ)
    else:
        env_map = dict(env)

    app_conf = _read_toml(root / "config" / "app.toml")
    strategy_conf = _read_toml(root / "config" / "strategy.toml")
    market_conf = _read_toml(root / "config" / "market_calendar.toml")
    codex_conf = _read_toml(root / "config" / "codex_review.toml")

    app_block = app_conf["app"]
    features_block = app_conf["features"]
    universe_block = app_conf["universe"]
    kis_block = app_conf["kis"]
    strategy_block = strategy_conf["strategy"]
    market_block = market_conf["market"]
    codex_block = codex_conf["codex_review"]

    trading_mode = env_map.get("TRADING_MODE", "paper").strip().lower()
    if trading_mode not in {"paper", "live"}:
        raise ValueError("TRADING_MODE must be either 'paper' or 'live'.")

    allow_live_orders = _env_bool(env_map, "ALLOW_LIVE_ORDERS", False)
    if allow_live_orders and trading_mode != "live":
        raise ValueError("ALLOW_LIVE_ORDERS=true requires TRADING_MODE=live.")

    strategy = StrategySettings(
        strategy_version=env_map.get("STRATEGY_VERSION", strategy_block["strategy_version"]),
        portfolio_version=env_map.get("PORTFOLIO_VERSION", strategy_block["portfolio_version"]),
        label_threshold_15=_env_float(env_map, "LABEL_THRESHOLD_15", strategy_block["label_threshold_15"]),
        label_threshold_60=_env_float(env_map, "LABEL_THRESHOLD_60", strategy_block["label_threshold_60"]),
        min_signal_confidence=_env_float(env_map, "MIN_SIGNAL_CONFIDENCE", strategy_block["min_signal_confidence"]),
        max_position_pct=_env_float(env_map, "MAX_POSITION_PCT", strategy_block["max_position_pct"]),
        max_open_positions=_env_int(env_map, "MAX_OPEN_POSITIONS", strategy_block["max_open_positions"]),
        slippage_bps=_env_float(env_map, "SLIPPAGE_BPS", strategy_block["slippage_bps"]),
        max_spread_bps=_env_float(env_map, "MAX_SPREAD_BPS", strategy_block["max_spread_bps"]),
        enable_paper_execution=_env_bool(env_map, "ENABLE_PAPER_EXECUTION", strategy_block["enable_paper_execution"]),
    )
    if not 0 < strategy.max_position_pct <= 1:
        raise ValueError("MAX_POSITION_PCT must be within (0, 1].")
    if strategy.max_open_positions <= 0:
        raise ValueError("MAX_OPEN_POSITIONS must be positive.")

    market = MarketCalendarSettings(
        timezone=env_map.get("APP_TIMEZONE", market_block["timezone"]),
        session_open=market_block["session_open"],
        new_entry_start=env_map.get("NEW_ENTRY_START", market_block["new_entry_start"]),
        new_entry_end=env_map.get("NEW_ENTRY_END", market_block["new_entry_end"]),
        forced_flat_time=env_map.get("FORCED_FLAT_TIME", market_block["forced_flat_time"]),
        session_close=market_block["session_close"],
    )
    parse_hhmm(market.session_open)
    parse_hhmm(market.new_entry_start)
    parse_hhmm(market.new_entry_end)
    parse_hhmm(market.forced_flat_time)
    parse_hhmm(market.session_close)

    codex_review = CodexReviewSettings(
        enabled=_env_bool(env_map, "CODEX_REVIEW_ENABLED", codex_block["enabled"]),
        report_dir=_env_path(root, env_map, "CODEX_REPORT_DIR", codex_block["report_dir"]),
        scope=env_map.get("CODEX_REVIEW_SCOPE", codex_block["scope"]),
    )

    kis_environment = KisEnvironmentSettings(
        hts_id=env_map.get("KIS_HTS_ID", kis_block["hts_id"]),
        customer_type=env_map.get("KIS_CUSTOMER_TYPE", kis_block["customer_type"]),
        rest_url_live=env_map.get("KIS_REST_URL_LIVE", kis_block["rest_url_live"]),
        rest_url_paper=env_map.get("KIS_REST_URL_PAPER", kis_block["rest_url_paper"]),
        ws_url_live=env_map.get("KIS_WS_URL_LIVE", kis_block["ws_url_live"]),
        ws_url_paper=env_map.get("KIS_WS_URL_PAPER", kis_block["ws_url_paper"]),
    )

    return AppSettings(
        project_root=root,
        app_name=env_map.get("APP_NAME", app_block["name"]),
        app_env=env_map.get("APP_ENV", app_block["environment"]),
        timezone=env_map.get("APP_TIMEZONE", app_block["timezone"]),
        runtime_data_dir=_env_path(root, env_map, "RUNTIME_DATA_DIR", app_block["runtime_data_dir"]),
        artifact_store=env_map.get("ARTIFACT_STORE", app_block["artifact_store"]),
        database_url=env_map.get("DATABASE_URL", app_block["database_url"]),
        trading_mode=trading_mode,
        allow_live_orders=allow_live_orders,
        kis_paper=_build_kis_credential_set(env_map, "PAPER"),
        kis_live=_build_kis_credential_set(env_map, "LIVE"),
        kis_environment=kis_environment,
        feature_set_version=env_map.get("FEATURE_SET_VERSION", features_block["feature_set_version"]),
        model_version_h15=env_map.get("MODEL_VERSION_H15", features_block["model_version_h15"]),
        model_version_h60=env_map.get("MODEL_VERSION_H60", features_block["model_version_h60"]),
        universe_selection_rule=env_map.get("UNIVERSE_SELECTION_RULE", universe_block["selection_rule"]),
        strategy=strategy,
        market_calendar=market,
        codex_review=codex_review,
    )
