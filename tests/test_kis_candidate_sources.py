from datetime import datetime, timedelta
import unittest

from app.universe.kis_candidate_sources import build_metadata, build_benchmark


class CandidateSourceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat("2026-10-14T10:00:00+09:00")
        self.master = dict(source="kis-stock-master-kospi-v1", reference_date="2026-10-14", output=dict(
            mksc_shrn_iscd="123456", scrt_grp_cls_code="ST", prst_cls_code="0", etp_prod_cls_code="0",
            etpr_undt_objt_co_yn="N", bstp_larg_div_code="0021", trht_yn="N", sltr_yn="N",
            mang_issu_yn="N", mrkt_alrm_cls_code="00", short_over_cls_code="0"))
        self.quote = dict(trade_date="2026-10-14", observed_at=self.now.isoformat(), output=dict(
            stck_shrn_iscd="123456", temp_stop_yn="N", sltr_yn="N", mang_issu_cls_code="N",
            invt_caful_yn="N", mrkt_warn_cls_code="00", short_over_yn="N"))

    def metadata(self):
        return build_metadata(self.master, self.quote, as_of=self.now)

    def test_ordinary_stock_and_sector_binding(self):
        m = self.metadata()
        self.assertEqual(m["market"], "KOSPI")
        self.assertEqual(m["sector_index_code"], "0021")
        self.assertEqual(m["market_index_code"], "0001")
        self.assertTrue(all(value is False for value in m["flags"].values()))

    def test_etf_and_preferred_and_spac_not_common(self):
        for key, value in (("scrt_grp_cls_code", "EF"), ("prst_cls_code", "1"), ("etpr_undt_objt_co_yn", "Y")):
            old = self.master["output"][key]
            self.master["output"][key] = value
            with self.assertRaises(ValueError):
                self.metadata()
            self.master["output"][key] = old

    def test_known_master_warning_keeps_true_flag(self):
        self.master["output"]["mrkt_alrm_cls_code"] = "02"
        self.assertTrue(self.metadata()["flags"]["investment_warning"])

    def test_unknown_code_and_missing_live_field_never_normal(self):
        self.quote["output"]["mrkt_warn_cls_code"] = "99"
        with self.assertRaises(ValueError):
            self.metadata()
        self.quote["output"]["mrkt_warn_cls_code"] = "00"
        self.quote["output"].pop("short_over_yn")
        with self.assertRaises(ValueError):
            self.metadata()

    def test_prior_reference_day_and_symbol_mismatch_blocked(self):
        self.master["reference_date"] = "2026-10-13"
        with self.assertRaises(ValueError):
            self.metadata()
        self.master["reference_date"] = "2026-10-14"
        self.quote["output"]["stck_shrn_iscd"] = "654321"
        with self.assertRaises(ValueError):
            self.metadata()

    def test_halt_and_overheat_union(self):
        self.quote["output"]["temp_stop_yn"] = "Y"
        self.master["output"]["short_over_cls_code"] = "1"
        m = self.metadata()
        self.assertTrue(m["flags"]["trading_halt"])
        self.assertTrue(m["flags"]["short_term_overheat"])

    def test_benchmark_codes_must_match_master(self):
        meta = self.metadata()
        def index(code, rate):
            return dict(trade_date="2026-10-14", observed_at=self.now.isoformat(),
                        index_code=code, output=dict(bstp_nmix_prdy_ctrt=str(rate)))
        result = build_benchmark(meta, index("0001", 1), index("0021", 2), as_of=self.now)
        self.assertEqual(result["sector_return_pct"], 2)
        with self.assertRaises(ValueError):
            build_benchmark(meta, index("0001", 1), index("2001", 2), as_of=self.now)

    def test_stale_quote_and_secret_redaction(self):
        before = self.metadata()
        self.quote["output"]["app_secret"] = "SECRET_FIXTURE"
        self.assertEqual(before, self.metadata())
        self.quote["observed_at"] = (self.now-timedelta(seconds=61)).isoformat()
        with self.assertRaises(ValueError):
            self.metadata()

    def test_kosdaq_and_watch_flag(self):
        self.master["source"] = "kis-stock-master-kosdaq-v1"
        self.master["output"]["invt_alrm_yn"] = "Y"
        m = self.metadata()
        self.assertEqual(m["market_index_code"], "1001")
        self.assertTrue(m["flags"]["investment_caution"])

    def test_market_benchmark_cannot_be_replaced_with_kospi200(self):
        meta = self.metadata()
        meta["market_index_code"] = "2001"
        def index(code):
            return dict(trade_date="2026-10-14", observed_at=self.now.isoformat(),
                        index_code=code, output=dict(bstp_nmix_prdy_ctrt="1"))
        with self.assertRaises(ValueError):
            build_benchmark(meta, index("2001"), index("0021"), as_of=self.now)

    def test_source_hash_cannot_contain_arbitrary_text(self):
        meta = self.metadata()
        meta["source_hash"] = "SECRET_FIXTURE"
        def index(code):
            return dict(trade_date="2026-10-14", observed_at=self.now.isoformat(),
                        index_code=code, output=dict(bstp_nmix_prdy_ctrt="1"))
        with self.assertRaises(ValueError):
            build_benchmark(meta, index("0001"), index("0021"), as_of=self.now)
