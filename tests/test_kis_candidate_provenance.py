from datetime import datetime, timedelta
import unittest

from app.universe.kis_candidate_provenance import parse_stock_master, build_minute_day_anchor


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.fromisoformat('2026-10-14T10:00:30+09:00')
        self.payload = {'rt_cd': '0', 'output2': [
            {'stck_bsop_date': '20261014', 'stck_cntg_hour': '100000'},
            {'stck_bsop_date': '20261014', 'stck_cntg_hour': '095900'}]}

    def anchor(self):
        return build_minute_day_anchor(self.payload, symbol='001440', received_at=self.now, as_of=self.now)

    def master(self, market='KOSPI'):
        tail = bytearray(b' ' * (227 if market == 'KOSPI' else 221))
        fields = [(0,b'ST'),(3,b'0021')]
        fields += ([(22,b'0'),(29,b'N'),(32,b'0'),(60,b'N'),(61,b'N'),(62,b'N'),(63,b'00'),(81,b'000000123456'),(158,b'0')]
                   if market=='KOSPI' else [(18,b'0'),(24,b'N'),(27,b'0'),(30,b'N'),(55,b'N'),(56,b'N'),(57,b'N'),(58,b'00'),(76,b'000000123456'),(153,b'0')])
        for offset,value in fields: tail[offset:offset+len(value)] = value
        return b'001440   KR7001440007'+ '대한전선'.encode('cp949') + tail + b'\r\n'

    def test_master_field_offsets_and_no_invented_reference_day(self):
        d = parse_stock_master(self.master(), market='KOSPI')
        self.assertIsNone(d['reference_date'])
        r=d['rows']['001440']
        self.assertEqual(r['bstp_larg_div_code'],'0021')
        self.assertEqual(r['prdy_vol'],'000000123456')
        self.assertEqual(r['prst_cls_code'],'0')
        self.assertEqual(r['mrkt_alrm_cls_code'],'00')
        self.assertEqual(len(d['source_hash']),64)

    def test_kosdaq_offsets_are_distinct(self):
        r=parse_stock_master(self.master('KOSDAQ'),market='KOSDAQ')['rows']['001440']
        self.assertEqual(r['invt_alrm_yn'],'N')
        self.assertEqual(r['mang_issu_yn'],'N')
        self.assertEqual(r['prdy_vol'],'000000123456')

    def test_truncated_duplicate_and_unknown_market_fail(self):
        for data,market in [(b'bad','KOSPI'),(self.master()*2,'KOSPI'),(self.master(),'OTHER')]:
            with self.assertRaises(ValueError):parse_stock_master(data,market=market)

    def test_unsupported_symbol_is_counted_not_coerced(self):
        data=b'0009K0   '+self.master()[9:]
        d=parse_stock_master(data,market='KOSPI')
        self.assertEqual(d['unsupported_symbol_rows'],1)
        self.assertEqual(d['rows'],{})

    def test_dated_minute_anchor_is_bound_to_request_symbol(self):
        a=self.anchor()
        self.assertEqual(a['trade_date'],'2026-10-14')
        self.assertEqual(a['symbol'],'001440')
        self.assertEqual(a['provider_at'],'2026-10-14T10:00:00+09:00')
        self.assertEqual(a['scope'],'same_symbol_minute_response_only')

    def test_prior_day_and_mixed_day_blocked(self):
        self.payload['output2'][1]['stck_bsop_date']='20261013'
        with self.assertRaises(ValueError):self.anchor()

    def test_future_and_stale_provider_blocked(self):
        for hour in ['100100','090000','256000']:
            self.payload['output2']=[{'stck_bsop_date':'20261014','stck_cntg_hour':hour}]
            with self.assertRaises(ValueError):self.anchor()

    def test_http_or_historical_date_cannot_replace_trade_day(self):
        self.payload['output2']=[{'d250_hgpr_date':'20261014','stck_cntg_hour':'100000'}]
        with self.assertRaises(ValueError):self.anchor()

    def test_stale_receipt_error_and_missing_output_blocked(self):
        with self.assertRaises(ValueError):
            build_minute_day_anchor(self.payload,symbol='001440',received_at=self.now-timedelta(seconds=21),as_of=self.now)
        self.payload['rt_cd']='1'
        with self.assertRaises(ValueError):self.anchor()

    def test_extra_secret_fields_do_not_enter_normalized_proof(self):
        a=self.anchor();self.payload['app_secret']='SECRET_FIXTURE'
        self.payload['output2'][0]['token']='SECRET_FIXTURE'
        self.assertEqual(self.anchor(),a)

    def test_blank_etp_field_is_preserved_not_assumed_zero(self):
        data=self.master()
        line=bytearray(data.rstrip(b'\r\n'));line[len(line)-227+22]=32
        row=parse_stock_master(bytes(line)+b'\n',market='KOSPI')['rows']['001440']
        self.assertEqual(row['etp_prod_cls_code'],'')

    def test_symbol_mismatch_and_duplicate_minute_are_blocked(self):
        self.payload['output2'][0]['stck_shrn_iscd']='006800'
        with self.assertRaises(ValueError):self.anchor()
        self.payload['output2']=[self.payload['output2'][1]]*2
        with self.assertRaises(ValueError):self.anchor()

    def test_nonaware_clock_and_holiday_blocked(self):
        with self.assertRaises(ValueError):
            build_minute_day_anchor(self.payload,symbol='001440',received_at=self.now,as_of=self.now.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            build_minute_day_anchor(self.payload,symbol='001440',received_at=self.now,as_of=self.now,holidays=('2026-10-14',))
