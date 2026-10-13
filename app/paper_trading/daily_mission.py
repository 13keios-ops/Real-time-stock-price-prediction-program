"""Isolated, cash-only KR momentum paper mission. Never imports a broker client."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from functools import wraps
from threading import RLock

from app.paper_trading.book import PaperPortfolioBook, PositionState
from app.paper_trading.costs import estimate_round_trip_cost_pct
from app.paper_trading.engine import PaperTradingEngine
from app.storage.contracts import MinuteBar, PaperOrder
from app.utils.time import get_timezone, now_local


MISSION_ID = "krw-300k-daily-10k"
MISSION_VERSION = "kr-volume-breakout-atr-trailing-v1"
MISSION_SUBDIRECTORY = Path("paper-missions") / MISSION_ID
KST = get_timezone("Asia/Seoul")


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _locked(method):
    @wraps(method)
    def synchronized(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return synchronized


@dataclass(frozen=True)
class MissionContract:
    start_date: str = "2026-10-14"
    initial_cash: float = 300000.0
    daily_net_target: float = 10000.0
    daily_loss_limit: float = 6000.0
    commission_rate: float = 0.00147
    sell_tax_rate: float = 0.002
    slippage_bps: float = 3.0
    spread_allowance_bps: float = 15.0
    symbols: tuple[str, ...] = ()
    holidays: tuple[str, ...] = ()
    version: str = MISSION_VERSION

    def __post_init__(self):
        date.fromisoformat(self.start_date)
        if self.version != MISSION_VERSION:
            raise ValueError("Unsupported mission contract version.")
        for name in ("initial_cash", "daily_net_target", "daily_loss_limit"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Invalid contract {name}.")
        if self.daily_loss_limit >= self.initial_cash:
            raise ValueError("Contract loss limit must be below starting capital.")
        for name in ("commission_rate", "sell_tax_rate", "slippage_bps", "spread_allowance_bps"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid contract {name}.")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("Contract needs a unique ordinary-stock universe.")
        if any(not s.isdigit() or len(s) != 6 for s in self.symbols):
            raise ValueError("Contract only supports six-digit domestic stock symbols.")
        for holiday in self.holidays:
            date.fromisoformat(holiday)

    def to_dict(self):
        return asdict(self)

    @property
    def sha256(self):
        return hashlib.sha256(_json(self.to_dict()).encode()).hexdigest()

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Mission contract must be an object.")
        copy = dict(value)
        copy["symbols"] = tuple(copy.get("symbols", ()))
        copy["holidays"] = tuple(copy.get("holidays", ()))
        return cls(**copy)


class DailyProfitMission:
    def __init__(self, folder: Path, contract: MissionContract):
        self._lock = RLock()
        self._stored_state_json = None
        self.folder = Path(folder)
        self.contract = contract
        self.folder.mkdir(parents=True, exist_ok=True)
        self.engine = PaperTradingEngine(commission_rate=contract.commission_rate,
                                        tax_rate=contract.sell_tax_rate,
                                        slippage_bps=contract.slippage_bps)
        database = self.folder / "mission.db"
        if database.is_symlink() or (database.exists() and database.stat().st_nlink != 1):
            raise ValueError("Mission database must be isolated, not a linked account.")
        self.connection = sqlite3.connect(database, timeout=0.25, check_same_thread=False)
        try:
            tables = {row[0] for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - {"mission_state", "mission_bars", "mission_events"}:
                raise ValueError("Mission database must be isolated; foreign tables found.")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS mission_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    contract_hash TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mission_bars (
                    symbol TEXT NOT NULL, bar_time TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    PRIMARY KEY(symbol, bar_time));
                CREATE TABLE IF NOT EXISTS mission_events (
                    seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            row = self.connection.execute("SELECT contract_hash,payload FROM mission_state WHERE singleton=1").fetchone()
            if row:
                if row[0] != contract.sha256:
                    raise ValueError("Mission contract changed; refusing to reset or mix the wallet.")
                self.state = json.loads(row[1])
                self._stored_state_json = row[1]
            else:
                self.state = dict(trade_date=None, day_start_cash=contract.initial_cash,
                                  cash=contract.initial_cash, realized=0.0, positions={},
                                  history={}, last_times={}, pending=None, position_meta={},
                                  days={}, blocking=[], fill_count=0, commission=0.0,
                                  tax=0.0, slippage=0.0, spread=0.0, source_bar_count=0, last_observed_at=None)
                with self.connection:
                    self._write_state(self.state)
        except Exception:
            self.connection.close()
            raise

    @_locked
    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _write_state(self, state):
        payload = _json(state)
        if self._stored_state_json is None:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO mission_state VALUES(1,?,?)", (self.contract.sha256, payload))
        else:
            cursor = self.connection.execute(
                "UPDATE mission_state SET payload=? WHERE singleton=1 AND contract_hash=? AND payload=?",
                (payload, self.contract.sha256, self._stored_state_json))
        if cursor.rowcount != 1:
            raise RuntimeError("Mission concurrent writer detected; refusing to overwrite wallet state.")
        self._stored_state_json = payload

    def _book(self, state):
        book = PaperPortfolioBook(self.contract.initial_cash, max_open_positions=1)
        book.cash_balance = state["cash"]
        book.realized_pnl_total = state["realized"]
        for symbol, value in state["positions"].items():
            row = dict(value)
            row["opened_at"] = datetime.fromisoformat(row["opened_at"]) if row["opened_at"] else None
            book.positions[symbol] = PositionState(**row)
        return book

    def _store_book(self, state, book):
        state["cash"] = book.cash_balance
        state["realized"] = book.realized_pnl_total
        state["positions"] = {
            symbol: {**asdict(p), "opened_at": p.opened_at.isoformat() if p.opened_at else None}
            for symbol, p in book.positions.items() if p.qty > 0
        }

    def _append(self, rows):
        self.connection.executemany("INSERT INTO mission_events(kind,payload) VALUES(?,?)",
                                    [(row["kind"], _json(row)) for row in rows])

    @_locked
    def events(self, *, kind=None):
        if kind:
            rows = self.connection.execute("SELECT payload FROM mission_events WHERE kind=? ORDER BY seq", (kind,))
        else:
            rows = self.connection.execute("SELECT payload FROM mission_events ORDER BY seq")
        return [json.loads(row[0]) for row in rows]

    def _liquidation_value(self, book):
        value = book.cash_balance
        for p in book.positions.values():
            price = p.last_price * (1 - (self.contract.slippage_bps + self.contract.spread_allowance_bps) / 10000)
            gross = p.qty * price
            value += gross - math.ceil(gross * self.contract.commission_rate) - math.ceil(gross * self.contract.sell_tax_rate)
        return value

    def _begin_day(self, state, day, book):
        if state["trade_date"] == day:
            return
        old = state["days"].get(state["trade_date"])
        if old is not None and book.open_position_count():
            old["status"] = "incomplete_open_position"
        state["trade_date"] = day
        state["day_start_cash"] = book.cash_balance
        carried = bool(book.open_position_count())
        state["days"][day] = dict(start_cash=book.cash_balance, status="collecting",
                                 halted=carried, halt_reason="overnight_position" if carried else None,
                                 basis_valid=not carried, source_bars=0, fills=0,
                                 commission=0.0, tax=0.0, slippage=0.0, spread=0.0)
        state["history"] = {}
        if state["pending"] and state["pending"]["side"] == "buy":
            state["pending"] = None

    def _order(self, state, bar, observed, side, qty, reason, *, stop_distance=0.0):
        available = observed.replace(second=0, microsecond=0) + timedelta(minutes=1)
        decision_id = f"{self.contract.sha256[:16]}:{bar.symbol}:{bar.bar_time.isoformat()}:{side}"
        state["pending"] = dict(symbol=bar.symbol, side=side, qty=qty, reason=reason,
                                decision_id=decision_id, decision_available_at=observed.isoformat(),
                                execute_at=available.isoformat(), signal_close=bar.close,
                                stop_distance=stop_distance)
        return dict(kind="decision", symbol=bar.symbol, event_time=observed.isoformat(),
                    source_bar_id=f"{bar.symbol}:{bar.bar_time.isoformat()}",
                    decision_id=decision_id, side=side, qty=qty, reason=reason,
                    execute_at=available.isoformat(), signal_close=bar.close)

    def _fill_pending(self, state, bar, book, rows, spread):
        pending = state["pending"]
        if not pending or pending["symbol"] != bar.symbol:
            return
        expected = datetime.fromisoformat(pending["execute_at"])
        if bar.bar_time < expected:
            return
        state["pending"] = None
        if bar.bar_time != expected:
            rows.append(dict(kind="cancel", event_time=bar.bar_time.isoformat(), symbol=bar.symbol,
                             reason="execution_bar_missing", decision_id=pending["decision_id"]))
            return
        side = pending["side"]
        if side == "buy" and (spread is None or not 0 <= spread <= 30):
            rows.append(dict(kind="cancel", event_time=bar.bar_time.isoformat(), reason="quote_unavailable"))
            return
        if side == "buy" and bar.open > pending["signal_close"] + pending["stop_distance"]:
            rows.append(dict(kind="cancel", event_time=bar.bar_time.isoformat(), reason="entry_gap_chase_blocked"))
            return
        qty = pending["qty"]
        if side == "sell":
            position = book.positions.get(bar.symbol)
            if not position or position.qty <= 0:
                return
            qty = position.qty
        price = bar.open * (1 + (self.contract.slippage_bps + self.contract.spread_allowance_bps) / 10000 * (1 if side == "buy" else -1))
        if side == "buy":
            while qty > 0 and qty * price + math.ceil(qty * price * self.contract.commission_rate) > book.cash_balance:
                qty -= 1
        if qty <= 0 or bar.volume < qty:
            rows.append(dict(kind="cancel", event_time=bar.bar_time.isoformat(), reason="cash_or_volume_insufficient"))
            return
        order_id = pending["decision_id"] + ":order"
        order = PaperOrder(order_id=order_id, symbol=bar.symbol, event_time=bar.bar_time,
                           side=side, qty=qty, limit_price=price, status="created")
        _, fill = self.engine.fill(order, price, order_id + ":event", order_id + ":fill")
        fill.commission = float(math.ceil(fill.commission))
        fill.tax = float(math.ceil(fill.tax))
        if side == "buy":
            book.apply_buy_fill(bar.symbol, fill, price)
            state["position_meta"][bar.symbol] = dict(peak_close=price, stop_distance=pending["stop_distance"])
        else:
            book.close_position(bar.symbol, fill, price)
            state["position_meta"].pop(bar.symbol, None)
        slippage = bar.open * qty * self.contract.slippage_bps / 10000
        spread_cost = bar.open * qty * self.contract.spread_allowance_bps / 10000
        for target in (state, state["days"][state["trade_date"]]):
            target["commission"] += fill.commission
            target["tax"] += fill.tax
            target["slippage"] += slippage
            target["spread"] += spread_cost
        state["fill_count"] += 1
        state["days"][state["trade_date"]]["fills"] += 1
        rows.append(dict(kind="fill", event_time=bar.bar_time.isoformat(), symbol=bar.symbol,
                         side=side, qty=qty, price=price, commission=fill.commission,
                         tax=fill.tax, slippage_cost=slippage, spread_cost=spread_cost, reason=pending["reason"],
                         decision_id=pending["decision_id"],
                         decision_available_at=pending["decision_available_at"]))

    def _update_history(self, state, bar):
        history = state["history"].setdefault(bar.symbol, dict(bars=[], atr=None, seed=[]))
        previous = history["bars"][-1]["close"] if history["bars"] else bar.open
        tr = max(bar.high - bar.low, abs(bar.high - previous), abs(bar.low - previous))
        if history["atr"] is None:
            history["seed"].append(tr)
            if len(history["seed"]) == 14:
                history["atr"] = sum(history["seed"]) / 14
                history["seed"] = []
        else:
            history["atr"] = (history["atr"] * 13 + tr) / 14
        history["bars"].append(dict(open=bar.open, high=bar.high, low=bar.low,
                                    close=bar.close, volume=bar.volume))
        history["bars"] = history["bars"][-20:]

    def _step(self, state, bar, observed, spread):
        book = self._book(state)
        self._begin_day(state, bar.bar_time.date().isoformat(), book)
        day = state["days"][state["trade_date"]]
        rows = [dict(kind="input", event_time=observed.isoformat(), symbol=bar.symbol,
                     source_bar_id=f"{bar.symbol}:{bar.bar_time.isoformat()}",
                     source_closed_at=(bar.bar_time + timedelta(minutes=1)).isoformat(),
                     quote_spread_bps=spread)]
        self._fill_pending(state, bar, book, rows, spread)
        book.mark_price(bar.symbol, bar.close)
        net = self._liquidation_value(book) - day["start_cash"]
        if net <= -self.contract.daily_loss_limit:
            day["halted"] = True
            day["halt_reason"] = "daily_loss_limit"
        if observed.time().replace(tzinfo=None) >= time(15, 14):
            day["halted"] = True
            day["halt_reason"] = day["halt_reason"] or "session_flatten"
        if not book.open_position_count() and day["basis_valid"] and book.cash_balance - day["start_cash"] >= self.contract.daily_net_target:
            day["halted"] = True
            day["halt_reason"] = "target_reached"
        position = book.positions.get(bar.symbol)
        reason = "warmup_or_no_breakout"
        if position and position.qty > 0 and not state["pending"]:
            meta = state["position_meta"][bar.symbol]
            meta["peak_close"] = max(meta["peak_close"], bar.close)
            distance = meta["stop_distance"] * (0.75 if net >= self.contract.daily_net_target else 1.0)
            held_minutes = (observed - position.opened_at).total_seconds() / 60
            exit_reason = day["halt_reason"] if day["halted"] else None
            if bar.close <= meta["peak_close"] - distance:
                exit_reason = exit_reason or "atr_trailing_stop"
            if held_minutes >= 60:
                exit_reason = exit_reason or "maximum_hold_time"
            if state["blocking"]:
                exit_reason = exit_reason or "source_evidence_blocked"
            if exit_reason:
                rows.append(self._order(state, bar, observed, "sell", position.qty, exit_reason))
                reason = exit_reason
            else:
                reason = "ride_momentum_with_trailing_stop"
        elif (not book.open_position_count() and not state["pending"] and not day["halted"]
              and not state["blocking"] and time(9, 30) <= observed.time().replace(tzinfo=None) < time(14, 45)):
            history = state["history"].get(bar.symbol, {})
            bars = history.get("bars", [])
            atr = history.get("atr") or 0.0
            if spread is None or not 0 <= spread <= 30:
                reason = "quote_unavailable_or_wide"
            elif len(bars) == 20 and atr > 0:
                past_high = max(b["high"] for b in bars)
                mean_volume = sum(b["volume"] for b in bars) / 20
                extension = bar.close - past_high
                minute_return = (bar.close / bar.open - 1) * 100
                if not (0.25 * atr <= extension <= 3 * atr and 0 < minute_return <= 3
                        and bar.volume >= mean_volume * 1.5):
                    reason = "breakout_volume_or_chase_filter"
                else:
                    stop_distance = max(2 * atr, bar.close * 0.006)
                    cost_rate = estimate_round_trip_cost_pct(
                        slippage_bps=self.contract.slippage_bps + self.contract.spread_allowance_bps,
                        commission_rate=self.contract.commission_rate,
                        sell_tax_rate=self.contract.sell_tax_rate) / 100
                    budget = min(book.cash_balance * 0.95, day["start_cash"] * 0.95)
                    remaining_risk = max(0, self.contract.daily_loss_limit + min(net, 0))
                    qty = min(int(budget / (bar.close * (1 + self.contract.commission_rate))),
                              int(remaining_risk / (stop_distance + bar.close * cost_rate)),
                              int(mean_volume * 0.01))
                    if qty > 0:
                        rows.append(self._order(state, bar, observed, "buy", qty,
                                                "price_volume_breakout", stop_distance=stop_distance))
                        reason = "price_volume_breakout"
                    else:
                        reason = "capital_risk_or_volume_zero"
        if len(rows) == 1 or reason != "price_volume_breakout":
            rows.append(dict(kind="observation", event_time=observed.isoformat(),
                             symbol=bar.symbol, reason=reason, close=bar.close))
        self._update_history(state, bar)
        state["last_times"][bar.symbol] = bar.bar_time.isoformat()
        state["last_observed_at"] = observed.isoformat()
        state["source_bar_count"] += 1
        day["source_bars"] += 1
        self._store_book(state, book)
        day["end_cash"] = book.cash_balance
        day["net_pnl"] = book.cash_balance - day["start_cash"] if not book.open_position_count() else None
        day["open_positions"] = book.open_position_count()
        day["status"] = (day["halt_reason"] if day["halted"] else "collecting")
        return rows

    @_locked
    def observe(self, bar: MinuteBar, *, observed_at: datetime, quote_spread_bps: float | None = None):
        if bar.bar_time.tzinfo is None or observed_at.tzinfo is None:
            return False
        observed = observed_at.astimezone(KST)
        values = bar.to_record()
        stamp = bar.bar_time.astimezone(KST)
        if (stamp.date().isoformat() < self.contract.start_date or stamp.weekday() >= 5
                or stamp.date().isoformat() in self.contract.holidays or bar.symbol not in self.contract.symbols):
            return False
        if self.state["trade_date"] and stamp.date().isoformat() < self.state["trade_date"]:
            return False
        prices = (bar.open, bar.high, bar.low, bar.close)
        if (not all(math.isfinite(p) and p > 0 for p in prices)
                or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
                or not math.isfinite(bar.volume) or not math.isfinite(bar.trade_count)
                or bar.volume < 0 or bar.trade_count <= 0 or stamp.second or stamp.microsecond):
            return False
        age = (observed - (stamp + timedelta(minutes=1))).total_seconds()
        if age < 0 or age > 120 or not time(9) <= stamp.time().replace(tzinfo=None) < time(15, 30):
            return False
        if quote_spread_bps is not None and not math.isfinite(quote_spread_bps):
            quote_spread_bps = None
        bar = MinuteBar(**{**values, "bar_time": stamp})
        fingerprint = hashlib.sha256(_json(bar.to_record()).encode()).hexdigest()
        seen = self.connection.execute("SELECT fingerprint FROM mission_bars WHERE symbol=? AND bar_time=?",
                                       (bar.symbol, stamp.isoformat())).fetchone()
        if seen:
            if seen[0] != fingerprint:
                state = json.loads(_json(self.state))
                if "conflicting_bar_identity" not in state["blocking"]:
                    state["blocking"].append("conflicting_bar_identity")
                if state["pending"] and state["pending"]["side"] == "buy":
                    state["pending"] = None
                with self.connection:
                    self._write_state(state)
                self.state = state
                self.write_report(as_of=observed)
            return False
        previous = self.state["last_times"].get(bar.symbol)
        if previous and stamp <= datetime.fromisoformat(previous):
            return False
        state = json.loads(_json(self.state))
        if previous and stamp > datetime.fromisoformat(previous) + timedelta(minutes=1):
            state["history"].pop(bar.symbol, None)
        with self.connection:
            rows = self._step(state, bar, observed, quote_spread_bps)
            self.connection.execute("INSERT INTO mission_bars VALUES(?,?,?)", (bar.symbol, stamp.isoformat(), fingerprint))
            self._append(rows)
            self._write_state(state)
        self.state = state
        self.write_report(as_of=observed)
        return True

    @_locked
    def mark_failed(self):
        state = json.loads(_json(self.state))
        if "mission_runtime_error" not in state["blocking"]:
            state["blocking"].append("mission_runtime_error")
        if state["pending"] and state["pending"]["side"] == "buy":
            state["pending"] = None
        with self.connection:
            self._write_state(state)
        self.state = state
        self.write_report()

    @_locked
    def report(self, *, as_of: datetime | None = None):
        as_of = (as_of or now_local("Asia/Seoul")).astimezone(KST)
        state = self.state
        book = self._book(state)
        day = state["days"].get(state["trade_date"])
        blocking = list(state["blocking"])
        for symbol, p in book.positions.items():
            stamp = state["last_times"].get(symbol)
            if not stamp or (as_of - datetime.fromisoformat(stamp) - timedelta(minutes=1)).total_seconds() > 120:
                blocking.append("stale_open_position_mark")
        if day and not day["basis_valid"]:
            blocking.append("overnight_position_invalid_day_basis")
        net = book.cash_balance - day["start_cash"] if day and day["basis_valid"] and not book.open_position_count() else None
        reached = bool(net is not None and net >= self.contract.daily_net_target and not blocking)
        status = ("target_reached" if reached else "evidence_blocked" if blocking
                  else day["status"] if day else "armed" if as_of.date().isoformat() < self.contract.start_date
                  else "awaiting_first_bar")
        return dict(
            version=MISSION_VERSION, mission_id=MISSION_ID, contract_hash=self.contract.sha256,
            generated_at=as_of.isoformat(), start_date=self.contract.start_date,
            initial_cash=self.contract.initial_cash, daily_net_target=self.contract.daily_net_target,
            daily_loss_limit=self.contract.daily_loss_limit, target_is_profit_cap=False,
            capital_refill=False, trade_date=state["trade_date"], day_status=status,
            target_reached=reached, new_entries_halted=bool(blocking or (day and day["halted"])),
            cash_balance=book.cash_balance, realized_net_pnl=book.realized_pnl_total,
            daily_net_pnl=net, open_positions=book.open_position_count(),
            net_liquidation_after_exit_costs=None if blocking else self._liquidation_value(book),
            pending_order_count=int(state["pending"] is not None), virtual_fill_count=state["fill_count"],
            commission=state["commission"], sell_tax=state["tax"], slippage_cost=state["slippage"], spread_cost=state["spread"],
            source_bar_count=state["source_bar_count"], symbols=list(self.contract.symbols),
            evidence_blocking_reasons=sorted(set(blocking)), daily_history=state["days"],
            cost_model=dict(version="kr-public-online-mission-20261013-v1",
                            commission_rate_per_side=self.contract.commission_rate,
                            commission_status="public_branch_online_tariff_assumed_not_account_verified",
                            sell_tax_rate=self.contract.sell_tax_rate,
                            slippage_bps_per_side=self.contract.slippage_bps,
                            spread_allowance_bps_per_side=self.contract.spread_allowance_bps,
                            spread_status="conservative_half_of_maximum_admitted_30bp_quote_spread",
                            slippage_status="research_assumption_not_observed_fill_calibration",
                            rounding="ceil_each_commission_and_tax_to_krw",
                            round_trip_cost_pct=estimate_round_trip_cost_pct(
                                slippage_bps=self.contract.slippage_bps + self.contract.spread_allowance_bps,
                                commission_rate=self.contract.commission_rate,
                                sell_tax_rate=self.contract.sell_tax_rate)),
            execution_model="completed_bar_open_proxy_after_decision_available_next_minute",
            safety=dict(broker_network_calls=0, broker_order_calls=0, broker_cancel_calls=0,
                        main_database_access="none", e7_policy_changed=False, leverage=False,
                        short_sales=False, no_actual_fill_guarantee=True),
        )

    @_locked
    def write_report(self, *, as_of: datetime | None = None):
        report = self.report(as_of=as_of)
        destinations = [self.folder / "latest.json"]
        if report["trade_date"]:
            destinations.append(self.folder / "days" / (report["trade_date"] + ".json"))
        for path in destinations:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(path)
        return report


def load_enabled_mission(runtime_root: Path, *, source: str, trading_mode: str):
    """Only the opted-in real KR paper feed can attach this separate wallet."""
    if source != "kis-ws" or trading_mode != "paper":
        return None
    root = Path(runtime_root).resolve()
    folder = root / MISSION_SUBDIRECTORY
    configuration = folder / "contract.json"
    if not configuration.exists():
        return None
    if folder.resolve() != folder or configuration.is_symlink():
        raise ValueError("Mission configuration must be isolated from other storage.")
    payload = json.loads(configuration.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
        raise ValueError("Mission enabled flag must be a boolean.")
    if not payload["enabled"]:
        return None
    return DailyProfitMission(folder, MissionContract.from_dict(payload["contract"]))
