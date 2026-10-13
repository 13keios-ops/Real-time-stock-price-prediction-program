"""Independent candidate wallets driven only by explicit captured observations."""

from datetime import datetime
import json
from pathlib import Path
from threading import RLock

from app.paper_trading.daily_mission import DailyProfitMission, MissionContract, _json
from app.universe.intraday_candidates import VERSION as SCANNER_VERSION, _hash
from app.universe.kis_candidate_snapshot import VERSION as ADAPTER_VERSION, scan_kis_snapshot


VERSION = "kr-intraday-comparison-v1"
STRATEGIES = ("breakout", "trend_pullback")


class _CandidateWallet(DailyProfitMission):
    def __init__(self, folder, contract, *, strategy, comparison_hash):
        self.strategy = strategy
        self.comparison_hash = comparison_hash
        self.context = None
        super().__init__(folder, contract)

    def _entry_reason(self, bar, bars, atr):
        if self.context and self.strategy in self.context["signals"]:
            return "price_volume_breakout" if self.strategy == "breakout" else "trend_pullback"
        return None

    def _order(self, state, bar, observed, side, qty, reason, *, stop_distance=0.0):
        row = super()._order(state, bar, observed, side, qty, reason, stop_distance=stop_distance)
        identity = f"{self.comparison_hash[:16]}:{self.strategy}:{row['decision_id']}"
        row["decision_id"] = state["pending"]["decision_id"] = identity
        row["comparison_hash"] = state["pending"]["comparison_hash"] = self.comparison_hash
        if side == "buy" and self.context:
            for key in ("candidate_id", "capture_hash"):
                row[key] = state["pending"][key] = self.context[key]
        return row

    def _fill_pending(self, state, bar, book, rows, spread):
        pending = state["pending"]
        if (pending and pending["side"] == "buy" and pending["symbol"] == bar.symbol
                and self.context and self.context.get("blocked")):
            rows.append(dict(kind="cancel", decision_id=pending["decision_id"],
                             reason="current_candidate_evidence_blocked", symbol=bar.symbol,
                             event_time=bar.bar_time.isoformat()))
            state["pending"] = None
            return
        super()._fill_pending(state, bar, book, rows, spread)

    def report(self, *, as_of=None):
        report = super().report(as_of=as_of)
        report["accounting_version"] = report["version"]
        report["version"] = VERSION
        report["mission_id"] = f"{VERSION}:{self.strategy}"
        report["strategy"] = self.strategy
        report["comparison_hash"] = self.comparison_hash
        report["runtime_attached"] = False
        return report


class CandidateComparison:
    """Replay/observe captured bars without changing any production subscription.

    The symbol universe and cost contract are immutable. New symbols require a new
    explicit comparison, not a mid-run wallet reset or silently changed universe.
    """
    def __init__(self, folder: Path, contract: MissionContract):
        self._lock = RLock()
        self.folder = Path(folder).absolute()
        if self.folder.resolve() != self.folder:
            raise ValueError("Comparison storage must not be symlinked")
        if self.folder.exists() and {p.name for p in self.folder.iterdir()} - set(STRATEGIES) - {"comparison.json", "latest-comparison.json"}:
            raise ValueError("Comparison storage contains a foreign account")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.contract = contract
        self.manifest = dict(version=VERSION, strategies=list(STRATEGIES),
                             scanner_version=SCANNER_VERSION, adapter_version=ADAPTER_VERSION,
                             wallet_contract=contract.to_dict(), sizing="cash95_daily_loss_and_volume_limited",
                             universe_changes="forbidden", runtime_attached=False)
        self.comparison_hash = _hash(self.manifest)
        manifest_file = self.folder / "comparison.json"
        if manifest_file.is_symlink():
            raise ValueError("Linked comparison contract")
        if manifest_file.exists():
            if _json(json.loads(manifest_file.read_text(encoding="utf-8"))) != _json(self.manifest):
                raise ValueError("Comparison contract drift; refusing to reset accounts")
        else:
            with manifest_file.open("x", encoding="utf-8") as handle:
                handle.write(_json(self.manifest))
        self.wallets = {}
        try:
            for strategy in STRATEGIES:
                child = self.folder / strategy
                if child.resolve() != child:
                    raise ValueError("Linked strategy wallet")
                self.wallets[strategy] = _CandidateWallet(child, contract, strategy=strategy,
                                                         comparison_hash=self.comparison_hash)
        except Exception:
            self.close()
            raise

    def close(self):
        for wallet in self.wallets.values():
            wallet.close()

    def observe(self, bar, *, observed_at: datetime, quote_spread_bps=None, capture=None):
        with self._lock:
            context = None
            spread = quote_spread_bps
            if capture is not None:
                result = scan_kis_snapshot(capture, as_of=observed_at, holidays=self.contract.holidays)
                raw_bar = capture.get("observations", {}).get(bar.symbol, {}).get("bars", [])
                if (not raw_bar or datetime.fromisoformat(raw_bar[-1]["bar_time"]) != bar.bar_time
                        or any(raw_bar[-1][key] != getattr(bar, key) for key in ("open", "high", "low", "close", "volume"))):
                    raise ValueError("Capture and observed bar identity mismatch")
                candidate = next((r for r in result["scanner"]["selected"] if r["symbol"] == bar.symbol), None)
                context = dict(signals=[], blocked=True)
                if candidate:
                    winners = {strategy: next((r["symbol"] for r in result["scanner"]["selected"]
                                               if strategy in r["signals"] and r["symbol"] in self.contract.symbols), None)
                               for strategy in STRATEGIES}
                    signals = [s for s in candidate["signals"] if winners[s] == bar.symbol]
                    context = dict(signals=signals, candidate_id=candidate["candidate_id"],
                                   capture_hash=result["source_hash"], blocked=False)
                    spread = candidate["spread_bps"]
            # Both wallets get the same closed-bar execution input, never the other's cash.
            responses = {}
            try:
                for strategy, wallet in self.wallets.items():
                    wallet.context = context
                    responses[strategy] = wallet.observe(bar, observed_at=observed_at, quote_spread_bps=spread)
            finally:
                for wallet in self.wallets.values():
                    wallet.context = None
            return responses

    def report(self, *, as_of=None):
        with self._lock:
            wallets = {strategy: wallet.report(as_of=as_of) for strategy, wallet in self.wallets.items()}
            counts = {wallet.state["source_bar_count"] for wallet in self.wallets.values()}
            return dict(version=VERSION, comparison_hash=self.comparison_hash,
                        wallets=wallets, status="consistent" if len(counts) == 1 else "partial_wallet_processing",
                        network_calls=0, order_calls=0, runtime_attached=False,
                        real_trading_enabled=False, profitability_validated=False,
                        account_balances_must_not_be_aggregated=True)
