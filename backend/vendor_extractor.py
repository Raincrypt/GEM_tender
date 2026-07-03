"""
vendor_extractor.py — Structured Vendor Profile Extraction
=============================================================
Automatically extracts structured fields from raw OCR document text:
  - Company identity (name, registration, GSTIN)
  - Certifications (ISO, BIS, MSME, Make-in-India)
  - Financial data (turnover, net worth)
  - Experience (years, past orders)
  - Key contacts and personnel

The structured profile is stored alongside the document in MongoDB
and used by the rule_engine and ai_risk_engine for accurate scoring
without guessing from free text.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("gem.vendor_extractor")

# Schema description sent to the LLM for structured extraction
VENDOR_SCHEMA = """
- company_name: Full legal company name (string or null)
- gem_reg_no: GeM registration number (string or null, format: GEM/V/...)
- gstin: GST Identification Number (string or null, 15-char alphanumeric)
- pan_number: PAN card number (string or null, XXXXX0000X format)
- msme_registered: Whether the company is MSME registered (true/false/null)
- msme_category: MSME category if applicable (Micro/Small/Medium or null)
- make_in_india: Whether Make-in-India certified (true/false/null)
- annual_turnover_cr: Annual turnover in Crores INR (number or null)
- net_worth_cr: Net worth in Crores INR (number or null)
- years_in_business: Number of years the company has been in business (integer or null)
- certifications: List of certifications mentioned, e.g. ["ISO 9001:2015", "BIS", "NABL"] (array or [])
- past_order_count: Number of past supply/work orders mentioned (integer or null)
- past_order_value_cr: Total value of past orders in Crores INR (number or null)
- primary_products: List of main products/services offered (array or [])
- authorized_dealer_of: OEM/Manufacturer this company is authorized dealer of (string or null)
- key_contact_name: Name of key contact person (string or null)
- registered_address_state: Indian state of registered address (string or null)
- financial_health: Overall financial health assessment based on data (Good/Moderate/Poor/Unknown)
"""

# Document-type-specific hints to improve extraction accuracy
DOC_TYPE_HINTS = {
    "maf": "This is a Manufacturer Authorization Form. Focus on: authorized dealer relationships, OEM names, product categories.",
    "financial": "This is a financial document. Focus on: turnover figures, net worth, CA certificate details, balance sheet data.",
    "iso": "This is a certification document. Focus on: ISO numbers, BIS registration, certificate validity dates.",
    "credential": "This is an experience credential. Focus on: past orders, purchase order numbers, work order values, client names.",
    "default": "This is a general procurement document. Extract all available vendor details.",
}


def _get_doc_type_hint(doc_type: str) -> str:
    """Return context hint based on document type."""
    if not doc_type:
        return DOC_TYPE_HINTS["default"]
    dt = doc_type.lower()
    for key, hint in DOC_TYPE_HINTS.items():
        if key in dt:
            return hint
    return DOC_TYPE_HINTS["default"]


def extract_vendor_profile(
    text: str,
    doc_type: str = "",
    existing_profile: Optional[dict] = None,
    file_path: Optional[str] = None
) -> dict:
    """
    Extract a structured vendor profile from OCR document text.

    Uses pdfplumber to parse financial tables if file_path is provided.
    Uses LLM for semantic extraction with fallback to regex patterns.
    If an existing_profile is provided, merges new data — existing
    non-null values are NOT overwritten (accumulate across documents).

    Args:
        text: Raw OCR text from the document
        doc_type: Document type hint (maf, financial, iso, credential, etc.)
        existing_profile: Previously extracted profile to merge into
        file_path: Optional physical path to the PDF document for table extraction

    Returns:
        Structured dict with all extracted vendor fields
    """
    if not text or len(text.strip()) < 50:
        return existing_profile or _empty_profile()

    # Try pdfplumber table extraction
    table_data = {}
    if file_path and file_path.lower().endswith(".pdf"):
        import os
        if os.path.exists(file_path):
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        tables = page.extract_tables()
                        for table in tables:
                            if not table or len(table) < 2:
                                continue
                            header_indices = {}
                            for r_idx, row in enumerate(table[:3]):
                                row_str = " ".join([str(c) for c in row if c is not None]).lower()
                                if "turnover" in row_str or "revenue" in row_str:
                                    for c_idx, cell in enumerate(row):
                                        cell_str = str(cell).lower()
                                        if "turnover" in cell_str or "revenue" in cell_str:
                                            header_indices["turnover"] = c_idx
                                if "worth" in row_str:
                                    for c_idx, cell in enumerate(row):
                                        cell_str = str(cell).lower()
                                        if "worth" in cell_str:
                                            header_indices["net_worth"] = c_idx
                            
                            if header_indices:
                                for row in table[1:]:
                                    clean_row = [str(c).strip() for c in row if c is not None]
                                    for key, col_idx in header_indices.items():
                                        if col_idx < len(clean_row):
                                            cell_val = clean_row[col_idx]
                                            num_match = re.search(r'\b([0-9,]+(?:\.[0-9]+)?)\b', cell_val)
                                            if num_match:
                                                try:
                                                    val = float(num_match.group(1).replace(",", ""))
                                                    if val > 0:
                                                        table_str = str(table).lower()
                                                        if "lakh" in table_str:
                                                            val = val / 100
                                                        elif "million" in table_str:
                                                            val = val / 10
                                                        if key == "turnover":
                                                            table_data["annual_turnover_cr"] = round(val, 2)
                                                        elif key == "net_worth":
                                                            table_data["net_worth_cr"] = round(val, 2)
                                                except Exception:
                                                    pass
                            else:
                                for row in table:
                                    clean_row = [str(c).strip() for c in row if c is not None]
                                    row_str = " ".join(clean_row).lower()
                                    if any(k in row_str for k in ("turnover", "revenue", "net worth", "worth")):
                                        for cell in clean_row:
                                            if re.search(r'\b20\d{2}\b', cell):
                                                continue
                                            num_match = re.search(r'\b([0-9,]+(?:\.[0-9]+)?)\b', cell)
                                            if num_match:
                                                try:
                                                    val = float(num_match.group(1).replace(",", ""))
                                                    if val > 0:
                                                        if "lakh" in row_str:
                                                            val = val / 100
                                                        elif "million" in row_str:
                                                            val = val / 10
                                                        if any(k in row_str for k in ("turnover", "revenue")):
                                                            table_data["annual_turnover_cr"] = round(val, 2)
                                                        elif "worth" in row_str:
                                                            table_data["net_worth_cr"] = round(val, 2)
                                                except Exception:
                                                    pass
            except Exception as e:
                logger.warning(f"[vendor_extractor] pdfplumber table extraction failed: {e}")

    try:
        import llm_client
        hint = _get_doc_type_hint(doc_type)
        schema_with_hint = f"{hint}\n\nExtract these fields:\n{VENDOR_SCHEMA}"
        extracted = llm_client.extract_structured(text, schema_with_hint, retries=2)
    except Exception as e:
        logger.warning(f"[vendor_extractor] LLM extraction failed, using regex fallback: {e}")
        extracted = {}

    # Regex fallback for key fields
    regex_data = _regex_extract(text)

    # Merge: table_data takes top priority, then LLM result, fill gaps with regex
    merged = {**regex_data, **{k: v for k, v in extracted.items() if v is not None}, **{k: v for k, v in table_data.items() if v is not None}}

    # Normalize data types
    merged = _normalize(merged)

    # Merge with existing profile (don't overwrite existing non-null values)
    if existing_profile:
        for key, val in existing_profile.items():
            if val is not None and val != [] and val != "":
                merged[key] = val

    return merged


def _empty_profile() -> dict:
    """Return a blank vendor profile template."""
    return {
        "company_name": None,
        "gem_reg_no": None,
        "gstin": None,
        "pan_number": None,
        "msme_registered": None,
        "msme_category": None,
        "make_in_india": None,
        "annual_turnover_cr": None,
        "net_worth_cr": None,
        "years_in_business": None,
        "certifications": [],
        "past_order_count": None,
        "past_order_value_cr": None,
        "primary_products": [],
        "authorized_dealer_of": None,
        "key_contact_name": None,
        "registered_address_state": None,
        "financial_health": "Unknown",
    }


def _regex_extract(text: str) -> dict:
    """Fast regex-based extraction as a fallback/supplement to LLM."""
    result = {}
    text_upper = text.upper()

    # GSTIN — 15-char pattern
    gstin_match = re.search(r'\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b', text)
    if gstin_match:
        result["gstin"] = gstin_match.group(1)

    # PAN
    pan_match = re.search(r'\b([A-Z]{5}[0-9]{4}[A-Z])\b', text)
    if pan_match:
        result["pan_number"] = pan_match.group(1)

    # GeM Registration
    gem_match = re.search(r'(GEM/[A-Z]/[A-Z0-9/]+)', text, re.IGNORECASE)
    if gem_match:
        result["gem_reg_no"] = gem_match.group(1)

    # MSME
    if "MSME" in text_upper or "UDYAM" in text_upper:
        result["msme_registered"] = True
        if "MICRO" in text_upper:
            result["msme_category"] = "Micro"
        elif "SMALL" in text_upper:
            result["msme_category"] = "Small"
        elif "MEDIUM" in text_upper:
            result["msme_category"] = "Medium"

    # Make in India
    if "MAKE IN INDIA" in text_upper or "MAKE-IN-INDIA" in text_upper:
        result["make_in_india"] = True

    # Certifications
    certs = []
    for cert_pattern in ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001", "BIS", "NABL", "CE MARK", "ROHS"]:
        if cert_pattern in text_upper:
            certs.append(cert_pattern)
    if certs:
        result["certifications"] = certs

    # Turnover (in crores)
    turnover_match = re.search(
        r'(?:annual\s+)?turnover[:\s]+(?:Rs\.?\s*|INR\s*|₹\s*)?([0-9,]+(?:\.[0-9]+)?)\s*(?:crore|cr|lakh)?',
        text, re.IGNORECASE
    )
    if not turnover_match:
        # Try pattern with unit when there are intermediate words (skipping year matches)
        turnover_match = re.search(
            r'(?:annual\s+)?turnover.*?(?:Rs\.?\s*|INR\s*|₹\s*)?([0-9,]+(?:\.[0-9]+)?)\s*(?:crore|cr|lakh|million)s?\b',
            text, re.IGNORECASE
        )
    if turnover_match:
        try:
            val = float(turnover_match.group(1).replace(",", ""))
            # Convert lakhs/millions to crores if needed
            context_area = text[max(0, turnover_match.start() - 10):min(len(text), turnover_match.end() + 20)].lower()
            if "lakh" in context_area:
                val = val / 100
            elif "million" in context_area:
                val = val / 10
            result["annual_turnover_cr"] = round(val, 2)
        except Exception:
            pass

    return result


def _normalize(data: dict) -> dict:
    """Normalize and validate extracted data types."""
    result = _empty_profile()
    result.update(data)

    # Type safety
    if result.get("annual_turnover_cr") is not None:
        try:
            result["annual_turnover_cr"] = round(float(str(result["annual_turnover_cr"]).replace(",", "")), 2)
        except Exception:
            result["annual_turnover_cr"] = None

    if result.get("net_worth_cr") is not None:
        try:
            result["net_worth_cr"] = round(float(str(result["net_worth_cr"]).replace(",", "")), 2)
        except Exception:
            result["net_worth_cr"] = None

    if result.get("years_in_business") is not None:
        try:
            result["years_in_business"] = int(result["years_in_business"])
        except Exception:
            result["years_in_business"] = None

    if not isinstance(result.get("certifications"), list):
        result["certifications"] = []

    if not isinstance(result.get("primary_products"), list):
        result["primary_products"] = []

    # Derive financial health score
    if result.get("annual_turnover_cr") and result["annual_turnover_cr"] > 10:
        result["financial_health"] = "Good"
    elif result.get("annual_turnover_cr") and result["annual_turnover_cr"] > 2:
        result["financial_health"] = "Moderate"
    elif result.get("annual_turnover_cr") is not None:
        result["financial_health"] = "Poor"

    return result


def summarize_profile(profile: dict) -> str:
    """Return a concise human-readable summary of the vendor profile."""
    parts = []
    if profile.get("company_name"):
        parts.append(f"Company: {profile['company_name']}")
    if profile.get("annual_turnover_cr"):
        parts.append(f"Turnover: ₹{profile['annual_turnover_cr']} Cr")
    if profile.get("years_in_business"):
        parts.append(f"Experience: {profile['years_in_business']} years")
    if profile.get("certifications"):
        parts.append(f"Certifications: {', '.join(profile['certifications'])}")
    if profile.get("msme_registered"):
        parts.append(f"MSME: {profile.get('msme_category', 'Yes')}")
    if profile.get("make_in_india"):
        parts.append("Make-in-India: Yes")
    if profile.get("financial_health"):
        parts.append(f"Financial Health: {profile['financial_health']}")
    return " | ".join(parts) if parts else "No profile data extracted."
