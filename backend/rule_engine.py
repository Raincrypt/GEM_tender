"""
rule_engine.py — Dynamic Rule Document Processing
====================================================
Instead of hardcoded Python scoring logic, this engine:

1. Reads uploaded tender/rule documents from the RAG index
2. Extracts scoring criteria using LLM -> structured RuleSet
3. Applies rules against extracted vendor profiles
4. Returns per-criterion verdicts WITH evidence citations

Example workflow:
  - Tender document says "Minimum 3 years experience in LED supply"
  - rule_engine extracts -> {"criterion": "Experience", "min_years": 3, "domain": "LED supply"}
  - Vendor profile says years_in_business=5, primary_products=["LED Displays"]
  - rule_engine applies -> {"pass": True, "score": 85, "evidence": "..."}
"""

import logging
import re
from typing import List, Optional

logger = logging.getLogger("gem.rule_engine")


# ─────────────────────────────────────────────────────────────────────────────
#  RULE EXTRACTION FROM DOCUMENTS
# ─────────────────────────────────────────────────────────────────────────────

RULE_SCHEMA = """
- criteria_name: Short name of the evaluation criterion (string)
- description: Full description of what is required (string)
- criterion_type: Type of criterion (Experience/Financial/Certification/Document/Technical/Compliance)
- is_mandatory: Whether this is a must-have disqualification criterion (true/false)
- min_years_experience: Minimum years of experience required (integer or null)
- min_turnover_cr: Minimum annual turnover in Crores required (number or null)
- required_certifications: List of required certifications, e.g. ["ISO 9001", "BIS"] (array or [])
- required_documents: List of required documents (array or [])
- scoring_basis: How scoring works for this criterion (e.g. "More experience = higher score") (string or null)
- max_score: Maximum score for this criterion out of 100 (number or null)
- keywords: Key terms that indicate this criterion is met (array or [])
"""


def extract_rules_from_document(text: str, tender_title: str = "") -> List[dict]:
    """
    Extract scoring criteria/rules from a tender or rule document.

    Args:
        text: Full text of the rule/tender document
        tender_title: Title of the tender for context

    Returns:
        List of structured rule dicts
    """
    if not text or len(text.strip()) < 100:
        return []

    try:
        import llm_client

        prompt = (
            f"You are an expert procurement officer reading a Government tender document.\n"
            f"Tender: '{tender_title}'\n\n"
            f"Extract ALL evaluation criteria and eligibility conditions from the text below.\n"
            f"For EACH criterion, return a JSON object with these fields:\n{RULE_SCHEMA}\n\n"
            f"Return a JSON object containing a single key 'rules', which holds the array of criteria objects, i.e. {{\"rules\": [...]}}. If no criteria are found, return {{\"rules\": []}}.\n\n"
            f"DOCUMENT TEXT:\n{text[:60000]}"
        )
        system = (
            "You are a procurement rules expert. Extract every criterion mentioned. "
            "Be thorough — include both mandatory eligibility conditions and scoring criteria. "
            "Return a valid JSON object with the key 'rules'."
        )
        raw_json_prompt = (
            f"{prompt}\n\n"
            "Return ONLY a valid JSON object. No explanation, no markdown."
        )
        
        result_dict = llm_client.generate_json(
            raw_json_prompt, system_instruction=system, temperature=0.0
        )
        
        rules = result_dict.get("rules", [])
        if isinstance(rules, list) and len(rules) > 0:
            logger.info(f"[rule_engine] Extracted {len(rules)} rules from document")
            return [_normalize_rule(r) for r in rules if isinstance(r, dict)]
    except Exception as e:
        logger.warning(f"[rule_engine] Rule extraction failed: {e}")

    # Fallback: use regex-based extraction
    return _regex_extract_rules(text)


def _normalize_rule(rule: dict) -> dict:
    """Normalize and validate a single rule dict."""
    normalized = {
        "criteria_name": str(rule.get("criteria_name", "Unknown Criterion")),
        "description": str(rule.get("description", "")),
        "criterion_type": str(rule.get("criterion_type", "Technical")),
        "is_mandatory": bool(rule.get("is_mandatory", False)),
        "min_years_experience": _safe_int(rule.get("min_years_experience")),
        "min_turnover_cr": _safe_float(rule.get("min_turnover_cr")),
        "required_certifications": rule.get("required_certifications", []) or [],
        "required_documents": rule.get("required_documents", []) or [],
        "scoring_basis": rule.get("scoring_basis"),
        "max_score": _safe_float(rule.get("max_score", 100)),
        "keywords": rule.get("keywords", []) or [],
    }
    if not isinstance(normalized["required_certifications"], list):
        normalized["required_certifications"] = []
    if not isinstance(normalized["required_documents"], list):
        normalized["required_documents"] = []
    return normalized


def _regex_extract_rules(text: str) -> List[dict]:
    """Fallback regex-based rule extraction for common patterns."""
    rules = []
    text_upper = text.upper()

    # Experience requirements
    exp_match = re.search(
        r'(?:minimum|atleast|at least|minimum of)?\s*(\d+)\s*(?:years?|yrs?).*?(?:experience|supply|work)',
        text, re.IGNORECASE
    )
    if exp_match:
        rules.append(_normalize_rule({
            "criteria_name": "Minimum Experience",
            "description": exp_match.group(0).strip(),
            "criterion_type": "Experience",
            "is_mandatory": True,
            "min_years_experience": int(exp_match.group(1)),
            "keywords": ["experience", "years"],
        }))

    # Turnover requirements
    turnover_match = re.search(
        r'(?:annual\s+)?turnover.*?(?:Rs\.?\s*|INR\s*|₹\s*)?(\d+(?:\.\d+)?)\s*(?:crore|cr)',
        text, re.IGNORECASE
    )
    if turnover_match:
        rules.append(_normalize_rule({
            "criteria_name": "Minimum Annual Turnover",
            "description": turnover_match.group(0).strip(),
            "criterion_type": "Financial",
            "is_mandatory": True,
            "min_turnover_cr": float(turnover_match.group(1)),
            "keywords": ["turnover", "financial", "crore"],
        }))

    # Certification requirements
    for cert in ["ISO 9001", "ISO 14001", "BIS", "NABL", "CE"]:
        if cert in text_upper:
            rules.append(_normalize_rule({
                "criteria_name": f"{cert} Certification",
                "description": f"{cert} certification required",
                "criterion_type": "Certification",
                "is_mandatory": "MANDATORY" in text_upper or "ESSENTIAL" in text_upper,
                "required_certifications": [cert],
                "keywords": [cert.lower(), "certification", "certificate"],
            }))

    return rules


# ─────────────────────────────────────────────────────────────────────────────
#  RULE APPLICATION AGAINST VENDOR PROFILES
# ─────────────────────────────────────────────────────────────────────────────

def apply_rules_to_vendor(rules: List[dict], vendor_profile: dict, vendor_name: str = "") -> dict:
    """
    Apply a set of extracted rules against a vendor's structured profile.

    Args:
        rules: List of rule dicts from extract_rules_from_document()
        vendor_profile: Structured vendor profile from vendor_extractor.py
        vendor_name: Vendor name for logging

    Returns:
        {
            "overall_pass": bool,
            "total_score": float,
            "max_possible_score": float,
            "score_pct": float,
            "verdicts": [per-rule verdict dicts],
            "failed_mandatory": [list of mandatory criteria that failed],
            "summary": str
        }
    """
    verdicts = []
    total_score = 0.0
    max_possible = 0.0
    failed_mandatory = []

    for rule in rules:
        verdict = _apply_single_rule(rule, vendor_profile)
        verdicts.append(verdict)

        rule_max = rule.get("max_score") or 100.0
        max_possible += rule_max
        total_score += verdict["score"]

        if rule.get("is_mandatory") and not verdict["pass"]:
            failed_mandatory.append(rule["criteria_name"])

    score_pct = round((total_score / max_possible * 100) if max_possible > 0 else 0.0, 2)
    overall_pass = len(failed_mandatory) == 0

    summary_parts = []
    if failed_mandatory:
        summary_parts.append(f"FAILED mandatory criteria: {', '.join(failed_mandatory)}")
    summary_parts.append(f"Score: {total_score:.1f}/{max_possible:.1f} ({score_pct:.1f}%)")

    return {
        "overall_pass": overall_pass,
        "total_score": round(total_score, 2),
        "max_possible_score": round(max_possible, 2),
        "score_pct": score_pct,
        "verdicts": verdicts,
        "failed_mandatory": failed_mandatory,
        "summary": " | ".join(summary_parts),
    }


def _apply_single_rule(rule: dict, profile: dict) -> dict:
    """Apply a single rule to a vendor profile. Returns a verdict dict."""
    rule_max = float(rule.get("max_score") or 100.0)
    criterion_type = rule.get("criterion_type", "").lower()
    passed = True
    score = rule_max  # Start with full marks, deduct based on failures
    evidence = []
    gaps = []

    # ── Experience check ──────────────────────────────────────────
    if rule.get("min_years_experience"):
        min_exp = rule["min_years_experience"]
        actual_exp = profile.get("years_in_business")
        
        # Check for MSME waiver eligibility under Government procurement guidelines
        if profile.get("msme_registered") is True:
            evidence.append(f"Experience: Waived (MSE registered; required: {min_exp} years)")
            score = min(score, rule_max)
        elif actual_exp is not None:
            if actual_exp >= min_exp:
                evidence.append(f"Experience: {actual_exp} years (required: {min_exp})")
                exp_score = min(1.0, actual_exp / min_exp) * rule_max
                score = min(score, exp_score)
            else:
                passed = False
                gaps.append(f"Insufficient experience: {actual_exp} years < {min_exp} required")
                score = 0.0 if rule.get("is_mandatory") else rule_max * 0.3
        else:
            evidence.append("Experience: not found in documents")
            score = rule_max * 0.5  # Unknown — partial credit

    # ── Turnover check ────────────────────────────────────────────
    if rule.get("min_turnover_cr"):
        min_turnover = rule["min_turnover_cr"]
        actual_turnover = profile.get("annual_turnover_cr")
        
        # Check for MSME waiver eligibility under Government procurement guidelines
        if profile.get("msme_registered") is True:
            evidence.append(f"Turnover: Waived (MSE registered; required: ₹{min_turnover}Cr)")
            score = min(score, rule_max)
        elif actual_turnover is not None:
            if actual_turnover >= min_turnover:
                evidence.append(f"Turnover: ₹{actual_turnover}Cr (required: ₹{min_turnover}Cr)")
                t_score = min(1.2, actual_turnover / min_turnover) * rule_max
                score = min(score, t_score)
            else:
                passed = False
                gaps.append(f"Turnover ₹{actual_turnover}Cr < required ₹{min_turnover}Cr")
                score = 0.0 if rule.get("is_mandatory") else rule_max * 0.2
        else:
            evidence.append("Turnover: not found in documents")
            score = min(score, rule_max * 0.5)

    # ── Certification check ───────────────────────────────────────
    required_certs = rule.get("required_certifications", [])
    if required_certs:
        vendor_certs = [c.upper() for c in (profile.get("certifications") or [])]
        missing_certs = [c for c in required_certs if not any(c.upper() in vc for vc in vendor_certs)]
        if missing_certs:
            gaps.append(f"Missing certifications: {', '.join(missing_certs)}")
            if rule.get("is_mandatory"):
                passed = False
                score = 0.0
            else:
                score = min(score, rule_max * (1 - len(missing_certs) / len(required_certs)))
        else:
            evidence.append(f"Certifications met: {', '.join(required_certs)}")

    # ── MSME / Make-in-India bonus check ──────────────────────────
    if "msme" in criterion_type or "msme" in rule.get("criteria_name", "").lower():
        if profile.get("msme_registered"):
            evidence.append("MSME registered: Yes")
        else:
            gaps.append("MSME registration not found")
            if rule.get("is_mandatory"):
                passed = False
                score = 0.0

    # ── Keyword-based check ───────────────────────────────────────
    keywords = rule.get("keywords", [])
    if keywords and not evidence and not gaps:
        # Generic check based on keywords matching profile
        profile_text = str(profile).lower()
        matched = [k for k in keywords if k.lower() in profile_text]
        if matched:
            evidence.append(f"Keywords matched: {', '.join(matched)}")
        else:
            score = min(score, rule_max * 0.6)

    score = max(0.0, min(rule_max, score))

    return {
        "criteria_name": rule["criteria_name"],
        "criterion_type": rule.get("criterion_type"),
        "is_mandatory": rule.get("is_mandatory", False),
        "pass": passed,
        "score": round(score, 2),
        "max_score": rule_max,
        "score_pct": round(score / rule_max * 100, 1) if rule_max else 0,
        "evidence": "; ".join(evidence) if evidence else "No direct evidence found",
        "gaps": gaps,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  HIGH-LEVEL: SCORE VENDOR AGAINST TENDER (end-to-end pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def score_vendor_against_tender(
    vendor_profile: dict,
    vendor_name: str,
    tender_criteria: list,
    rag_doc_chunks: Optional[List[str]] = None
) -> dict:
    """
    Full pipeline: apply both structured rule-based scoring AND
    RAG-context LLM scoring for each criterion.

    Args:
        vendor_profile: Structured profile from vendor_extractor.py
        vendor_name: Vendor display name
        tender_criteria: List of EvaluationCriteria objects (with .name, .max_score)
        rag_doc_chunks: Optional list of raw text chunks from RAG for this vendor

    Returns:
        Full scoring result with both rule-based and LLM-based scores
    """
    results = []

    for criteria in tender_criteria:
        criteria_name = getattr(criteria, "name", str(criteria))
        max_score = float(getattr(criteria, "max_score", 100))

        # Step 1: LLM scoring with evidence (using RAG chunks)
        llm_result = {"score": 0.0, "rationale": "No LLM scoring available",
                      "evidence_quote": "N/A", "confidence": 0, "needs_human_review": True}
        if rag_doc_chunks:
            try:
                import llm_client
                llm_result = llm_client.score_with_evidence(
                    criteria_name, max_score, rag_doc_chunks, vendor_name
                )
            except Exception as e:
                logger.warning(f"[rule_engine] LLM scoring failed for {criteria_name}: {e}")

        # Step 2: Profile-based quick check
        profile_hint = _quick_profile_check(criteria_name, vendor_profile, max_score)

        # Step 3: Combine — LLM score weighted 70%, profile check 30%
        if llm_result["confidence"] >= 60:
            final_score = llm_result["score"] * 0.7 + profile_hint["score"] * 0.3
        else:
            # Low confidence — trust profile check more
            final_score = llm_result["score"] * 0.4 + profile_hint["score"] * 0.6

        final_score = round(min(max_score, max(0.0, final_score)), 2)

        results.append({
            "criteria_name": criteria_name,
            "max_score": max_score,
            "final_score": final_score,
            "llm_score": llm_result["score"],
            "llm_confidence": llm_result["confidence"],
            "evidence_quote": llm_result["evidence_quote"],
            "rationale": llm_result["rationale"],
            "profile_score": profile_hint["score"],
            "profile_notes": profile_hint["notes"],
            "needs_human_review": llm_result["needs_human_review"],
        })

    total = sum(r["final_score"] for r in results)
    max_total = sum(r["max_score"] for r in results)
    return {
        "vendor_name": vendor_name,
        "total_score": round(total, 2),
        "max_score": round(max_total, 2),
        "score_pct": round(total / max_total * 100, 2) if max_total else 0,
        "criteria_results": results,
        "needs_review_count": sum(1 for r in results if r["needs_human_review"]),
    }


def _quick_profile_check(criteria_name: str, profile: dict, max_score: float) -> dict:
    """Quick profile-based scoring for a criteria name using keyword matching."""
    name_lower = criteria_name.lower()
    score = max_score * 0.5  # neutral baseline
    notes = []

    if any(k in name_lower for k in ["experience", "years", "track record"]):
        years = profile.get("years_in_business")
        if years:
            ratio = min(1.0, years / 5.0)
            score = max_score * (0.5 + ratio * 0.5)
            notes.append(f"{years} years experience")

    elif any(k in name_lower for k in ["turnover", "financial", "net worth"]):
        turnover = profile.get("annual_turnover_cr")
        if turnover:
            ratio = min(1.0, turnover / 10.0)
            score = max_score * (0.4 + ratio * 0.6)
            notes.append(f"₹{turnover}Cr turnover")

    elif any(k in name_lower for k in ["iso", "certification", "quality"]):
        certs = profile.get("certifications", [])
        if certs:
            score = max_score * min(1.0, 0.6 + len(certs) * 0.1)
            notes.append(f"Certifications: {', '.join(certs[:3])}")
        else:
            score = max_score * 0.3
            notes.append("No certifications found")

    elif any(k in name_lower for k in ["msme", "startup"]):
        if profile.get("msme_registered"):
            score = max_score
            notes.append("MSME registered")
        else:
            score = 0.0
            notes.append("Not MSME registered")

    elif any(k in name_lower for k in ["make in india", "domestic", "local"]):
        if profile.get("make_in_india"):
            score = max_score
            notes.append("Make-in-India certified")

    return {"score": round(score, 2), "notes": "; ".join(notes) if notes else "General assessment"}


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except Exception:
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except Exception:
        return None
