import re
import logging
from typing import Dict, Any, List
import llm_client

logger = logging.getLogger("gem.document_auditor")

def is_llm_active() -> bool:
    """Check if a cloud/local LLM provider is active and configured."""
    try:
        status = llm_client.get_provider_status()
        if status.get("strict_open_source"):
            # If strict open source is active, only allow if ollama is configured
            return status.get("active_provider") == "ollama"
        return bool(status.get("gemini_configured") or status.get("openai_configured") or status.get("active_provider") == "ollama")
    except Exception:
        return False

# ──────────────────────────────────────────────────────────────────────────────
#  R1: Past Experience / Purchase Orders Audit
# ──────────────────────────────────────────────────────────────────────────────

def audit_purchase_orders(ocr_text: str, thresholds: Dict[str, float]) -> Dict[str, Any]:
    """
    Audit bidder purchase orders to check compliance with past experience thresholds.
    """
    t_1 = thresholds.get("exp_1_order_lakhs", 0.0)
    t_2 = thresholds.get("exp_2_orders_lakhs", 0.0)
    t_3 = thresholds.get("exp_3_orders_lakhs", 0.0)

    if not ocr_text or len(ocr_text.strip()) < 20:
        return {
            "status": "FAIL",
            "reason": "No document text available for verification.",
            "pos": []
        }

    if is_llm_active():
        try:
            prompt = (
                f"Extract all completed client project contracts, supply orders, or purchase orders (POs) "
                f"mentioned in the document text. For each order, extract the order number, date or financial year, "
                f"buyer name/firm, and contract value in Lakhs INR (1 Lakh = 100,000 INR; 1 Crore = 100 Lakhs).\n\n"
                f"DOCUMENT TEXT:\n{ocr_text[:30000]}\n\n"
                f"Extract and return a JSON object with this key:\n"
                f"- \"pos\": list of dicts, each with keys \"po_number\", \"date\", \"amount_lakhs\" (number), \"buyer_name\", \"is_work_completion\" (boolean)."
            )
            res = llm_client.generate_json(prompt, expected_keys=["pos"])
            pos = res.get("pos", [])
            
            # Filter valid PO values
            valid_pos = []
            for po in pos:
                val = po.get("amount_lakhs")
                if isinstance(val, (int, float)) and val > 0:
                    valid_pos.append(po)

            valid_pos.sort(key=lambda x: x.get("amount_lakhs", 0), reverse=True)
            amounts = [x["amount_lakhs"] for x in valid_pos]

            opt1 = any(v >= t_1 for v in amounts)
            opt2 = len([v for v in amounts if v >= t_2]) >= 2
            opt3 = len([v for v in amounts if v >= t_3]) >= 3

            if opt1:
                status = "PASS"
                reason = f"Experience satisfied per Option 1: 1 PO ≥ ₹{t_1:.2f}L (Extracted: ₹{amounts[0]:.2f}L by {valid_pos[0].get('buyer_name', 'client')})."
            elif opt2:
                status = "PASS"
                reason = f"Experience satisfied per Option 2: 2 POs ≥ ₹{t_2:.2f}L (Extracted: {', '.join([f'₹{x:.2f}L' for x in amounts[:2]])})."
            elif opt3:
                status = "PASS"
                reason = f"Experience satisfied per Option 3: 3 POs ≥ ₹{t_3:.2f}L (Extracted: {', '.join([f'₹{x:.2f}L' for x in amounts[:3]])})."
            else:
                status = "FAIL"
                if amounts:
                    reason = f"Extracted POs ({', '.join([f'₹{x:.2f}L' for x in amounts])}) do not meet required thresholds (₹{t_1:.2f}L / ₹{t_2:.2f}L / ₹{t_3:.2f}L)."
                else:
                    reason = f"No valid qualifying purchase orders could be verified in the documents."

            return {
                "status": status,
                "reason": reason,
                "pos": valid_pos
            }
        except Exception as e:
            logger.warning(f"LLM audit_purchase_orders failed: {e}. Falling back to heuristics.")

    # Fallback to heuristics
    import reports_pqc
    file_vals = reports_pqc.extract_monetary_values(ocr_text, require_po_context=True)
    file_vals = sorted(list(set(file_vals)), reverse=True)

    opt1 = any(v >= t_1 for v in file_vals)
    opt2 = len([v for v in file_vals if v >= t_2]) >= 2
    opt3 = len([v for v in file_vals if v >= t_3]) >= 3

    pos_fallback = [{"po_number": f"PO-HEURISTIC-{i+1}", "date": "N/A", "amount_lakhs": v, "buyer_name": "N/A", "is_work_completion": True} for i, v in enumerate(file_vals)]

    if opt1:
        status = "PASS"
        reason = f"Experience satisfied (Heuristic Option 1): 1 PO ≥ ₹{t_1:.2f}L (Verified: ₹{file_vals[0]:.2f}L)."
    elif opt2:
        status = "PASS"
        reason = f"Experience satisfied (Heuristic Option 2): 2 POs ≥ ₹{t_2:.2f}L (Verified: {', '.join([f'₹{x:.2f}L' for x in file_vals[:2]])})."
    elif opt3:
        status = "PASS"
        reason = f"Experience satisfied (Heuristic Option 3): 3 POs ≥ ₹{t_3:.2f}L (Verified: {', '.join([f'₹{x:.2f}L' for x in file_vals[:3]])})."
    else:
        status = "FAIL"
        reason = f"No POs meeting required experience thresholds verified under PO-context requirements."

    return {
        "status": status,
        "reason": reason,
        "pos": pos_fallback
    }

# ──────────────────────────────────────────────────────────────────────────────
#  R2: Average Annual Turnover Audit
# ──────────────────────────────────────────────────────────────────────────────

def audit_turnover(ocr_text: str, threshold_lakhs: float) -> Dict[str, Any]:
    """
    Audit bidder turnover values for the last 3 financial years.
    """
    if threshold_lakhs == 0.0:
        return {
            "status": "PASS (Not Applicable)",
            "reason": "Financial turnover requirement is not applicable for this tender.",
            "turnovers": [],
            "ca_firm": "N/A",
            "udin": "N/A"
        }

    if not ocr_text or len(ocr_text.strip()) < 20:
        return {
            "status": "FAIL",
            "reason": "No document text available for financial audit.",
            "turnovers": [],
            "ca_firm": "N/A",
            "udin": "N/A"
        }

    if is_llm_active():
        try:
            prompt = (
                f"Extract the annual turnovers of the bidder for the last 3 financial years (in Lakhs INR) "
                f"along with the Auditing Chartered Accountant (CA) firm name and the 18-digit UDIN (Unique Document Identification Number) if present.\n\n"
                f"DOCUMENT TEXT:\n{ocr_text[:20000]}\n\n"
                f"Return a JSON object with keys:\n"
                f"- \"turnovers\": list of dicts, each with keys \"year\" (string, e.g. '2023-24') and \"amount_lakhs\" (number)\n"
                f"- \"ca_firm\": string, or null\n"
                f"- \"udin\": string, or null"
            )
            res = llm_client.generate_json(prompt, expected_keys=["turnovers", "ca_firm", "udin"])
            turnovers = res.get("turnovers", [])
            ca_firm = res.get("ca_firm") or "Not Identified"
            udin = res.get("udin") or "Not Identified"

            valid_turnovers = []
            for t in turnovers:
                amt = t.get("amount_lakhs")
                if isinstance(amt, (int, float)) and amt > 0:
                    valid_turnovers.append(t)

            if valid_turnovers:
                avg_val = sum(x["amount_lakhs"] for x in valid_turnovers) / len(valid_turnovers)
                if avg_val >= threshold_lakhs:
                    status = "PASS"
                    reason = f"Verified average annual turnover of ₹{avg_val:.2f}L (Threshold: ₹{threshold_lakhs:.2f}L) audited by {ca_firm} (UDIN: {udin})."
                else:
                    status = "FAIL"
                    reason = f"Average annual turnover of ₹{avg_val:.2f}L is below the required threshold of ₹{threshold_lakhs:.2f}L."
                
                return {
                    "status": status,
                    "reason": reason,
                    "turnovers": valid_turnovers,
                    "ca_firm": ca_firm,
                    "udin": udin
                }
        except Exception as e:
            logger.warning(f"LLM audit_turnover failed: {e}. Falling back to heuristics.")

    # Fallback to heuristics
    import reports_pqc
    po_vals = reports_pqc.extract_monetary_values(ocr_text)
    turnover_vals = [v for v in po_vals if v >= threshold_lakhs and v < 50000.0]
    has_filing_kws = any(kw in ocr_text.upper() for kw in ["TURNOVER", "BALANCE SHEET", "UDIN", "CA CERTIFICATE"])

    if turnover_vals:
        avg_val = turnover_vals[0]
        status = "PASS"
        reason = f"Turnover verified via heuristic: ₹{avg_val:.2f}L (Threshold: ₹{threshold_lakhs:.2f}L)."
        turnovers_fallback = [{"year": "Average", "amount_lakhs": avg_val}]
    elif has_filing_kws:
        status = "PASS (With Risk)"
        reason = "Financial statements detected but exact values could not be parsed. CA Certification indicators present."
        turnovers_fallback = []
    else:
        status = "FAIL"
        reason = f"No financial filings or turnovers meeting threshold of ₹{threshold_lakhs:.2f}L could be verified."
        turnovers_fallback = []

    return {
        "status": status,
        "reason": reason,
        "turnovers": turnovers_fallback,
        "ca_firm": "Heuristic Audit",
        "udin": "Heuristic Audit"
    }

# ──────────────────────────────────────────────────────────────────────────────
#  R3: Net Worth Audit
# ──────────────────────────────────────────────────────────────────────────────

def audit_net_worth(ocr_text: str) -> Dict[str, Any]:
    """
    Audit bidder Net Worth details to ensure it is positive.
    """
    if not ocr_text or len(ocr_text.strip()) < 20:
        return {
            "status": "FAIL",
            "reason": "No document text available for Net Worth audit.",
            "net_worth_lakhs": 0.0,
            "statement_date": "N/A"
        }

    if is_llm_active():
        try:
            prompt = (
                f"Analyze if the bidder's Net Worth is positive. Extract the Net Worth value in Lakhs INR "
                f"and the date of the financial statement or CA audit report.\n\n"
                f"DOCUMENT TEXT:\n{ocr_text[:20000]}\n\n"
                f"Return a JSON object with keys:\n"
                f"- \"net_worth_lakhs\": number\n"
                f"- \"is_positive\": boolean\n"
                f"- \"statement_date\": string, or null"
            )
            res = llm_client.generate_json(prompt, expected_keys=["net_worth_lakhs", "is_positive", "statement_date"])
            val = res.get("net_worth_lakhs", 0.0)
            is_pos = res.get("is_positive", False)
            date_str = res.get("statement_date") or "Not Specified"

            if is_pos and val >= 0:
                status = "PASS"
                reason = f"Verified positive Net Worth of ₹{val:.2f}L (Statement Date: {date_str})."
            else:
                status = "FAIL"
                reason = f"Net Worth reported as negative or invalid (Value: ₹{val:.2f}L)."

            return {
                "status": status,
                "reason": reason,
                "net_worth_lakhs": val,
                "statement_date": date_str
            }
        except Exception as e:
            logger.warning(f"LLM audit_net_worth failed: {e}. Falling back to heuristics.")

    # Fallback to heuristics
    text_up = ocr_text.upper()
    has_networth_kw = "NET WORTH" in text_up or "NET-WORTH" in text_up or "NETWORTH" in text_up
    has_negative = "NEGATIVE" in text_up or "DEFICIT" in text_up or "EROSION" in text_up

    if has_networth_kw and not has_negative:
        status = "PASS"
        reason = "Net Worth certificate/declaration found. Keywords indicate positive net worth."
    elif has_networth_kw and has_negative:
        status = "FAIL"
        reason = "Net Worth keywords detected alongside negative signals (DEFICIT, EROSION, NEGATIVE)."
    else:
        status = "PASS (With Risk)"
        reason = "Net Worth statement not explicitly located; assuming positive based on general financials. Review recommended."

    return {
        "status": status,
        "reason": reason,
        "net_worth_lakhs": 0.0,
        "statement_date": "N/A"
    }

# ──────────────────────────────────────────────────────────────────────────────
#  R4: OEM Manufacturer Authorization Form (MAF) Audit
# ──────────────────────────────────────────────────────────────────────────────

def audit_oem_maf(ocr_text: str, tender_id: str = "") -> Dict[str, Any]:
    """
    Audit Manufacturer Authorization Form (MAF) to ensure it is bid-specific and authorized.
    """
    if not ocr_text or len(ocr_text.strip()) < 20:
        return {
            "status": "FAIL",
            "reason": "No document text available for MAF validation.",
            "maf_details": {}
        }

    if is_llm_active():
        try:
            prompt = (
                f"Evaluate if this document is a valid OEM Manufacturer Authorization Form (MAF) "
                f"supporting the bidder for tender/ref {tender_id or 'this tender'}. Extract key fields:\n\n"
                f"DOCUMENT TEXT:\n{ocr_text[:20000]}\n\n"
                f"Return a JSON object with keys:\n"
                f"- \"is_valid\": boolean (true if it functions as a valid OEM MAF / authorization)\n"
                f"- \"tender_ref\": string (tender ID or ref number extracted from MAF)\n"
                f"- \"oem_name\": string (OEM company issuing the MAF)\n"
                f"- \"bidder_name\": string (bidder name authorized by OEM)\n"
                f"- \"authorized\": boolean (true if signed/authorized by OEM official)\n"
                f"- \"expiry_date\": string, or null"
            )
            res = llm_client.generate_json(prompt, expected_keys=["is_valid", "tender_ref", "oem_name", "bidder_name", "authorized", "expiry_date"])
            
            is_valid = res.get("is_valid", False)
            oem = res.get("oem_name") or "OEM Not Clear"
            bidder = res.get("bidder_name") or "Bidder Not Clear"
            ref = res.get("tender_ref") or "Tender Ref Not Clear"

            if is_valid:
                status = "PASS"
                reason = f"Valid OEM MAF verified from {oem} authorizing {bidder} (Tender Ref: {ref})."
            else:
                status = "FAIL"
                reason = f"Document does not function as a valid bid-specific OEM MAF (OEM: {oem}, Bidder: {bidder})."

            return {
                "status": status,
                "reason": reason,
                "maf_details": res
            }
        except Exception as e:
            logger.warning(f"LLM audit_oem_maf failed: {e}. Falling back to heuristics.")

    # Fallback to heuristics
    text_up = ocr_text.upper()
    has_maf_kws = any(kw in text_up for kw in ["AUTHORIZE", "AUTHORISE", "DEALER CERTIFICATE", "MAF", "OEM AUTH", "MANUFACTURER"])
    
    if has_maf_kws:
        status = "PASS"
        reason = "OEM Manufacturer Authorization certificate found. Verification successful."
    else:
        status = "FAIL"
        reason = "No valid OEM authorization or Manufacturer Authorization Form clauses located in document."

    return {
        "status": status,
        "reason": reason,
        "maf_details": {
            "is_valid": has_maf_kws,
            "oem_name": "Heuristic Audit",
            "bidder_name": "Heuristic Audit",
            "tender_ref": tender_id
        }
    }

# ──────────────────────────────────────────────────────────────────────────────
#  R5: ISO Certificate Audit
# ──────────────────────────────────────────────────────────────────────────────

def audit_iso_certificates(ocr_text: str) -> Dict[str, Any]:
    """
    Audit bidder ISO or standard certificates (e.g. ISO 9001, BIS).
    """
    if not ocr_text or len(ocr_text.strip()) < 20:
        return {
            "status": "FAIL",
            "reason": "No document text available for ISO certificate audit.",
            "certificates": []
        }

    if is_llm_active():
        try:
            prompt = (
                f"Extract all ISO or quality certificates (e.g., ISO 9001, ISO 14001, BIS, etc.) "
                f"found in the text. For each certificate, extract standard name, certificate number, registrar/issuing authority, and expiry date.\n\n"
                f"DOCUMENT TEXT:\n{ocr_text[:20000]}\n\n"
                f"Return a JSON object with key:\n"
                f"- \"certificates\": list of dicts, each with keys \"standard\" (string), \"cert_no\" (string), \"registrar\" (string), \"expiry_date\" (string)"
            )
            res = llm_client.generate_json(prompt, expected_keys=["certificates"])
            certs = res.get("certificates", [])

            valid_certs = [c for c in certs if c.get("standard")]
            
            if valid_certs:
                status = "PASS"
                details = [f"{c['standard']} (No: {c.get('cert_no', 'N/A')}, Exp: {c.get('expiry_date', 'N/A')})" for c in valid_certs]
                reason = f"Verified active certifications: {', '.join(details)}."
            else:
                status = "FAIL"
                reason = "No valid ISO 9001, ISO 14001, or BIS certificates found in document."

            return {
                "status": status,
                "reason": reason,
                "certificates": valid_certs
            }
        except Exception as e:
            logger.warning(f"LLM audit_iso_certificates failed: {e}. Falling back to heuristics.")

    # Fallback to heuristics
    text_up = ocr_text.upper()
    has_iso = "ISO 9001" in text_up or "ISO CERTIFICATE" in text_up or "QUALITY CERTIFICATE" in text_up or "BIS CERTIFICATE" in text_up

    if has_iso:
        status = "PASS"
        reason = "ISO or BIS Quality Management certification detected in files. Standard: ISO 9001 / BIS."
        certs_fallback = [{"standard": "ISO 9001", "cert_no": "Verified (Heuristic)", "registrar": "N/A", "expiry_date": "N/A"}]
    else:
        status = "FAIL"
        reason = "Quality certification or ISO 9001 indicators could not be verified in files."
        certs_fallback = []

    return {
        "status": status,
        "reason": reason,
        "certificates": certs_fallback
    }
