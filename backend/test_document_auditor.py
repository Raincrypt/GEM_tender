import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import document_auditor

class TestDocumentAuditor(unittest.TestCase):

    @patch('document_auditor.is_llm_active', return_value=True)
    @patch('llm_client.generate_json')
    def test_audit_purchase_orders_llm_pass(self, mock_generate_json, mock_is_llm_active):
        mock_generate_json.return_value = {
            "pos": [
                {"po_number": "PO-100", "date": "2024-01-15", "amount_lakhs": 25.5, "buyer_name": "Entity A", "is_work_completion": True},
                {"po_number": "PO-101", "date": "2024-02-15", "amount_lakhs": 15.0, "buyer_name": "Entity B", "is_work_completion": True}
            ]
        }
        thresholds = {
            "exp_1_order_lakhs": 20.0,
            "exp_2_orders_lakhs": 12.0,
            "exp_3_orders_lakhs": 8.0
        }
        res = document_auditor.audit_purchase_orders("dummy text", thresholds)
        self.assertEqual(res["status"], "PASS")
        self.assertIn("Entity A", res["reason"])
        self.assertEqual(len(res["pos"]), 2)

    @patch('document_auditor.is_llm_active', return_value=True)
    @patch('llm_client.generate_json')
    def test_audit_turnover_llm_pass(self, mock_generate_json, mock_is_llm_active):
        mock_generate_json.return_value = {
            "turnovers": [
                {"year": "2021-22", "amount_lakhs": 45.0},
                {"year": "2022-23", "amount_lakhs": 55.0},
                {"year": "2023-24", "amount_lakhs": 50.0}
            ],
            "ca_firm": "CA & Associates",
            "udin": "24123456AAAA1234"
        }
        res = document_auditor.audit_turnover("dummy text", 40.0)
        self.assertEqual(res["status"], "PASS")
        self.assertIn("CA & Associates", res["reason"])
        self.assertIn("24123456AAAA1234", res["reason"])

    @patch('document_auditor.is_llm_active', return_value=True)
    @patch('llm_client.generate_json')
    def test_audit_net_worth_llm(self, mock_generate_json, mock_is_llm_active):
        mock_generate_json.return_value = {
            "net_worth_lakhs": 12.5,
            "is_positive": True,
            "statement_date": "2024-03-31"
        }
        res = document_auditor.audit_net_worth("dummy text")
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(res["net_worth_lakhs"], 12.5)

    @patch('document_auditor.is_llm_active', return_value=True)
    @patch('llm_client.generate_json')
    def test_audit_oem_maf_llm(self, mock_generate_json, mock_is_llm_active):
        mock_generate_json.return_value = {
            "is_valid": True,
            "tender_ref": "TENDER-123",
            "oem_name": "SuperOEM",
            "bidder_name": "SuperBidder",
            "authorized": True,
            "expiry_date": "2026-12-31"
        }
        res = document_auditor.audit_oem_maf("dummy text", "TENDER-123")
        self.assertEqual(res["status"], "PASS")
        self.assertIn("SuperOEM", res["reason"])

    @patch('document_auditor.is_llm_active', return_value=True)
    @patch('llm_client.generate_json')
    def test_audit_iso_certificates_llm(self, mock_generate_json, mock_is_llm_active):
        mock_generate_json.return_value = {
            "certificates": [
                {"standard": "ISO 9001:2015", "cert_no": "ISO-9876", "registrar": "TUV", "expiry_date": "2027-01-01"}
            ]
        }
        res = document_auditor.audit_iso_certificates("dummy text")
        self.assertEqual(res["status"], "PASS")
        self.assertEqual(len(res["certificates"]), 1)

    @patch('document_auditor.is_llm_active', return_value=False)
    def test_heuristics_fallbacks(self, mock_is_llm_active):
        # R3 Net Worth fallback positive
        res_nw = document_auditor.audit_net_worth("Net Worth is healthy. Balance Sheet.")
        self.assertEqual(res_nw["status"], "PASS")
        
        # R3 Net Worth fallback negative
        res_nw_fail = document_auditor.audit_net_worth("Net Worth is negative.")
        self.assertEqual(res_nw_fail["status"], "FAIL")

        # R5 ISO fallback
        res_iso = document_auditor.audit_iso_certificates("ISO 9001 certificate is attached.")
        self.assertEqual(res_iso["status"], "PASS")

if __name__ == '__main__':
    unittest.main()
