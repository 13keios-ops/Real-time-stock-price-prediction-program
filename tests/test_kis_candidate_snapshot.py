import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import timedelta
import unittest

from app.universe.kis_candidate_snapshot import scan_kis_snapshot
from app.universe.kis_candidate_sources import VERSION as SOURCE_VERSION
from tests import test_intraday_candidates as fixtures


class KisCandidateSnapshotTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.IntradayCandidatesTests()
        fixture.setUp()
        self.now = fixture.now
        stamp = self.now.isoformat()
        self.snapshot = dict(source="kis-volume-rank-krx-v1", trade_date=self.now.date().isoformat(),
                             received_at=stamp, rows=[dict(mksc_shrn_iscd="123456", acml_vol="2000", prdy_vol="1000", vol_inrt="200")],
                             observations={"123456": dict(
                                 price=dict(received_at=stamp, trade_date=self.now.date().isoformat(),
                                            output=dict(stck_prpr="25000", prdy_ctrt="3", acml_tr_pbmn="2000000000")),
                                 orderbook=dict(received_at=stamp, provider_at=stamp,
                                                output1=dict(askp1="25000", bidp1="24950")),
                                 metadata=dict(observed_at=stamp, trade_date=self.now.date().isoformat(),
                                               market="KOSDAQ", instrument_type="common_stock",
                                               flags={key: False for key in ("investment_caution", "investment_warning", "investment_risk",
                                                                             "management", "liquidation", "trading_halt", "short_term_overheat")}),
                                 benchmark=dict(observed_at=stamp, trade_date=self.now.date().isoformat(),
                                                market_return_pct=1, sector_return_pct=2),
                                 bars=fixture.row["bars"])})
        self.snapshot['source_binding_version']=SOURCE_VERSION
        obs=self.snapshot['observations']['123456']
        obs['metadata'].update(source_version=SOURCE_VERSION,source_hash='a'*64)
        obs['benchmark'].update(source_version=SOURCE_VERSION,source_hash='b'*64,metadata_source_hash='a'*64)
        obs['price']['output'].update(stck_shrn_iscd='123456',temp_stop_yn='N',sltr_yn='N',
            mang_issu_cls_code='N',invt_caful_yn='N',short_over_yn='N',mrkt_warn_cls_code='00')

    def scan(self):
        return scan_kis_snapshot(self.snapshot, as_of=self.now)

    def test_explicit_volume_denominator_and_lineage(self):
        result = self.scan()
        self.assertEqual(result["scanner"]["selected"][0]["volume_ratio"], 2)
        self.assertEqual(result["volume_ratio_basis"], "accumulated_volume_over_previous_day_volume")
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(len(result["source_hash"]), 64)

    def test_reported_percent_is_not_used_as_ratio(self):
        self.snapshot["rows"][0]["vol_inrt"] = "99999"
        self.assertEqual(self.scan()["scanner"]["selected"][0]["volume_ratio"], 2)

    def test_alphanumeric_symbol_excluded_without_blocking_numeric(self):
        self.snapshot["rows"].append(dict(mksc_shrn_iscd="0009K0"))
        result = self.scan()
        self.assertEqual(len(result["scanner"]["selected"]), 1)
        self.assertEqual(result["adapter_rejections"][0]["reason"], "unsupported_symbol_contract")

    def test_missing_previous_volume_blocks(self):
        self.snapshot["rows"][0].pop("prdy_vol")
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_missing_quote_is_not_fabricated(self):
        self.snapshot["observations"]["123456"].pop("orderbook")
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_margin_code_does_not_prove_safety(self):
        metadata = self.snapshot["observations"]["123456"]["metadata"]
        metadata.pop("flags")
        metadata["iscd_stat_cls_code"] = "55"
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_warning_and_unknown_flags_block(self):
        for value in (True, None, "N", 0):
            self.snapshot["observations"]["123456"]["metadata"]["flags"]["investment_warning"] = value
            self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_old_quote_provider_time_blocks_despite_fresh_receipt(self):
        self.snapshot["observations"]["123456"]["orderbook"]["provider_at"] = (self.now-timedelta(days=1)).isoformat()
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_prior_day_snapshot_is_not_relabelled(self):
        self.snapshot["trade_date"] = "2026-10-13"
        with self.assertRaises(ValueError):
            self.scan()

    def test_future_benchmark_blocks(self):
        self.snapshot["observations"]["123456"]["benchmark"]["observed_at"] = (self.now+timedelta(seconds=1)).isoformat()
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_duplicate_symbol_blocks_whole_source(self):
        self.snapshot["rows"].append(copy.deepcopy(self.snapshot["rows"][0]))
        with self.assertRaises(ValueError):
            self.scan()

    def test_secret_not_echoed_or_in_lineage(self):
        before = self.scan()
        self.snapshot["appsecret"] = "SECRET_FIXTURE"
        self.snapshot["observations"]["123456"]["price"]["output"]["token"] = "SECRET_FIXTURE"
        self.assertEqual(before, self.scan())
        self.assertNotIn("SECRET_FIXTURE", str(self.scan()))

    def test_scanner_semantic_filters_are_still_applied(self):
        self.snapshot["observations"]["123456"]["price"]["output"]["prdy_ctrt"] = "-2"
        self.assertIn("relative_strength", self.scan()["scanner"]["rejected"][0]["reasons"])

    def test_holiday_blocks(self):
        with self.assertRaises(ValueError):
            scan_kis_snapshot(self.snapshot, as_of=self.now, holidays=("2026-10-14",))

    def test_malformed_metadata_is_per_symbol_rejection(self):
        self.snapshot["observations"]["123456"]["metadata"] = "not_an_object"
        self.assertEqual(self.scan()["scanner"]["selected"], [])

    def test_cli_accepts_kis_capture(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / ".tmp-tests") as folder:
            path = Path(folder) / "capture.json"
            path.write_text(json.dumps(self.snapshot), encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "scripts/scan_intraday_candidates.py"),
                                     "--snapshot", str(path), "--as-of", self.now.isoformat(),
                                     "--format", "kis-capture"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["adapter_version"], "kis-intraday-snapshot-adapter-v1")
