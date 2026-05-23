import json
import unittest

from app.brokers.kis_response_redaction import (
    REDACTED,
    find_unredacted_sensitive_paths,
    redact_kis_json_text,
    redact_kis_payload,
)


class KisResponseRedactionTests(unittest.TestCase):
    def test_redacts_credentials_and_account_identifiers_but_keeps_order_fields(self) -> None:
        payload = {
            "authorization": "Bearer live-token",
            "appkey": "live-app-key",
            "appsecret": "live-app-secret",
            "CANO": "12345678",
            "ACNT_PRDT_CD": "01",
            "output1": [
                {
                    "odno": "0000000001",
                    "ord_no": "0000000002",
                    "pdno": "005930",
                    "shtn_pdno": "005930",
                    "ord_qty": "3",
                    "avg_prvs": "70000",
                    "cust_name": "sample-owner",
                    "ctac_tlno": "01012345678",
                    "inqr_ip_addr": "192.0.2.10",
                    "ordr_empno": "employee-1",
                }
            ],
        }

        redacted = redact_kis_payload(payload)

        self.assertEqual(redacted["authorization"], REDACTED)
        self.assertEqual(redacted["appkey"], REDACTED)
        self.assertEqual(redacted["appsecret"], REDACTED)
        self.assertEqual(redacted["CANO"], REDACTED)
        self.assertEqual(redacted["ACNT_PRDT_CD"], REDACTED)
        self.assertEqual(redacted["output1"][0]["cust_name"], REDACTED)
        self.assertEqual(redacted["output1"][0]["ctac_tlno"], REDACTED)
        self.assertEqual(redacted["output1"][0]["inqr_ip_addr"], REDACTED)
        self.assertEqual(redacted["output1"][0]["ordr_empno"], REDACTED)
        self.assertEqual(redacted["output1"][0]["odno"], "0000000001")
        self.assertEqual(redacted["output1"][0]["ord_no"], "0000000002")
        self.assertEqual(redacted["output1"][0]["pdno"], "005930")
        self.assertEqual(redacted["output1"][0]["shtn_pdno"], "005930")
        self.assertEqual(redacted["output1"][0]["ord_qty"], "3")
        self.assertEqual(find_unredacted_sensitive_paths(redacted), [])

    def test_redact_kis_json_text_outputs_valid_json(self) -> None:
        text = json.dumps({"access_token": "secret", "output": [{"pdno": "000660"}]})

        redacted_text = redact_kis_json_text(text)
        redacted = json.loads(redacted_text)

        self.assertEqual(redacted["access_token"], REDACTED)
        self.assertEqual(redacted["output"][0]["pdno"], "000660")

    def test_find_unredacted_sensitive_paths_reports_remaining_sensitive_values(self) -> None:
        payload = {
            "output": [
                {
                    "authorization": "Bearer token",
                    "pdno": "005930",
                    "ctac_tlno": REDACTED,
                }
            ]
        }

        findings = find_unredacted_sensitive_paths(payload)

        self.assertEqual(findings, ["$.output[0].authorization"])


if __name__ == "__main__":
    unittest.main()
