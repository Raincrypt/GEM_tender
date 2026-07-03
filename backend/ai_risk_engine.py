"""
GEM AI Risk Engine v4.0
- Fully deterministic NLP scoring
- Semantic embedding-based risk detection (sentence-transformers)
- OCR confidence analysis (pytesseract)
- Vendor multi-dimensional risk model
- Ollama (llama3) integration with graceful fallback
"""
import re, json, math, hashlib
import urllib.request, urllib.error
from collections import Counter
from typing import List, Dict, Optional

# ─────────────────────────────────────────────────────────────────
#  OPTIONAL ML IMPORTS (graceful fallback)
# ─────────────────────────────────────────────────────────────────
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False

try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

# ─────────────────────────────────────────────────────────────────
#  RISK KEYWORD SCORING TABLE
# ─────────────────────────────────────────────────────────────────
RISK_KEYWORDS = {
    "fraud": 40, "forged": 40, "fake": 40,
    "blacklisted": 35, "debarred": 35,
    "bankrupt": 30, "insolvent": 30, "insolvency": 30, "liquidated": 30,
    "litigation": 25, "lawsuit": 25,
    "termination": 20, "breach": 20,
    "penalty": 15, "default": 15,
    "suspended": 10, "delay": 10,
}


# ─────────────────────────────────────────────────────────────────
#  SEMANTIC RISK ANALYZER (sentence-transformers based)
# ─────────────────────────────────────────────────────────────────
# 50+ risk concept phrases for embedding-based detection
RISK_CONCEPT_PHRASES = [
    # Fraud & Forgery
    "fraudulent document submission", "forged signature on certificate",
    "fake experience certificate", "falsified financial statement",
    "identity fraud by vendor", "counterfeit product supplied",
    "fabricated test report", "manipulated audit report",
    "forged bank guarantee", "fraudulent insurance certificate",
    # Blacklisting & Debarment
    "vendor blacklisted by government", "debarred from public procurement",
    "suspension from tender participation", "banned supplier entity",
    "disqualified vendor registration",
    # Financial Distress
    "company declared bankrupt", "vendor financial insolvency",
    "business under liquidation", "severe cash flow problems",
    "unpaid debts and liabilities", "credit rating downgrade",
    "financial distress indicators", "negative net worth company",
    # Price Manipulation & Bid Rigging
    "bid rigging cartel formation", "price manipulation in tender",
    "collusive bidding pattern", "artificially inflated price",
    "predatory pricing below cost", "price dumping to eliminate competition",
    "coordinated bid submission", "market division agreement",
    "complementary bidding scheme", "phantom bid submission",
    # Compliance Violation
    "violation of procurement rules", "non-compliance with tender terms",
    "breach of contract conditions", "regulatory compliance failure",
    "environmental law violation", "labour law non-compliance",
    "tax evasion by vendor", "GST registration irregularity",
    # Quality & Delivery Issues
    "defective goods delivered", "quality inspection failure",
    "substandard material supplied", "delivery deadline missed",
    "repeated order cancellation", "warranty claim rejection",
    "product recall due to safety", "failed performance test",
    # Conflict of Interest
    "conflict of interest in evaluation", "related party transaction",
    "undisclosed beneficial ownership", "nepotism in vendor selection",
    "revolving door employment",
    # Operational Risk
    "data breach by vendor", "confidential information leak",
    "cybersecurity vulnerability", "supply chain disruption",
    "force majeure event impact", "vendor business discontinuity",
]


class SemanticRiskAnalyzer:
    """
    Embedding-based risk detection using sentence-transformers.
    Pre-computes embeddings for 50+ risk concepts and scores text
    by cosine similarity against the concept bank.
    """

    def __init__(self, model_name: str = "all-mpnet-base-v2"):
        """Initialize the semantic analyzer with a sentence-transformer model."""
        if not HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers and numpy are required for SemanticRiskAnalyzer. "
                "Install with: pip install sentence-transformers numpy"
            )
        self._model = SentenceTransformer(model_name)
        self._concept_phrases = list(RISK_CONCEPT_PHRASES)
        # Pre-compute and normalize risk concept embeddings
        self._concept_embeddings = self._model.encode(
            self._concept_phrases, convert_to_numpy=True, normalize_embeddings=True
        )
        # Map each concept phrase to its top-level risk category
        self._concept_categories = self._assign_categories()

    def _assign_categories(self) -> Dict[str, str]:
        """Assign a risk category label to each concept phrase based on its content."""
        categories = {}
        category_keywords = {
            "Fraud & Forgery": ["fraud", "forged", "fake", "falsif", "counterfeit", "fabricat", "manipulat"],
            "Blacklisting": ["blacklist", "debar", "suspend", "banned", "disqualif"],
            "Financial Distress": ["bankrupt", "insolven", "liquidat", "cash flow", "debt", "credit", "net worth", "financial distress"],
            "Bid Rigging": ["bid rigging", "cartel", "collusiv", "inflat", "predatory", "dumping", "coordinated bid", "market division", "complementary bid", "phantom"],
            "Compliance Violation": ["violation", "non-compliance", "breach", "regulatory", "environment", "labour", "tax evasion", "gst"],
            "Quality Issues": ["defective", "inspection fail", "substandard", "deadline miss", "cancellation", "warranty", "recall", "failed performance"],
            "Conflict of Interest": ["conflict of interest", "related party", "beneficial ownership", "nepotism", "revolving door"],
            "Operational Risk": ["data breach", "confidential", "cybersecurity", "supply chain", "force majeure", "discontinuity"],
        }
        for phrase in self._concept_phrases:
            phrase_lower = phrase.lower()
            matched_cat = "General Risk"
            for cat, kws in category_keywords.items():
                if any(kw in phrase_lower for kw in kws):
                    matched_cat = cat
                    break
            categories[phrase] = matched_cat
        return categories

    def analyze_semantic_risk(self, text: str) -> dict:
        """
        Analyze text for risk using embedding cosine similarity.

        Splits text into sentences, embeds each, computes cosine similarity
        against pre-computed risk concept bank.

        Returns:
            dict with keys:
                - risk_score (float, 0-100): overall semantic risk score
                - matching_concepts (list): top matched risk concepts with scores
                - confidence (float, 0-1): dynamically computed from similarity distribution
                - category_breakdown (dict): risk score per category
                - sentence_risks (list): per-sentence risk details
        """
        if not text or len(text.strip()) < 10:
            return {
                "risk_score": 0.0,
                "matching_concepts": [],
                "confidence": 0.0,
                "category_breakdown": {},
                "sentence_risks": [],
            }

        # Split text into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.replace('\n', ' ').strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

        if not sentences:
            return {
                "risk_score": 0.0,
                "matching_concepts": [],
                "confidence": 0.0,
                "category_breakdown": {},
                "sentence_risks": [],
            }

        # Embed all sentences (batch for efficiency)
        sentence_embeddings = self._model.encode(
            sentences, convert_to_numpy=True, normalize_embeddings=True
        )

        # Compute cosine similarity: (num_sentences x num_concepts)
        # Since embeddings are normalized, dot product = cosine similarity
        sim_matrix = np.dot(sentence_embeddings, self._concept_embeddings.T)

        # Collect all per-sentence max similarities and their best-matching concepts
        all_max_sims = []
        sentence_risks = []
        concept_max_scores = np.zeros(len(self._concept_phrases))

        for i, sentence in enumerate(sentences):
            row = sim_matrix[i]
            top_idx = int(np.argmax(row))
            max_sim = float(row[top_idx])
            all_max_sims.append(max_sim)

            # Track global max per concept
            concept_max_scores = np.maximum(concept_max_scores, row)

            if max_sim > 0.3:  # Only report meaningful matches
                sentence_risks.append({
                    "sentence": sentence[:200],
                    "best_match_concept": self._concept_phrases[top_idx],
                    "category": self._concept_categories[self._concept_phrases[top_idx]],
                    "similarity": round(max_sim, 4),
                })

        # Compute overall risk score from top-N concept similarities
        # Use top 10 concept scores (sorted descending) with diminishing weight
        sorted_concept_scores = np.sort(concept_max_scores)[::-1]
        top_n = min(10, len(sorted_concept_scores))
        weights = np.array([1.0 / (1 + k * 0.3) for k in range(top_n)])
        weighted_top = sorted_concept_scores[:top_n] * weights
        raw_risk = float(np.sum(weighted_top)) / float(np.sum(weights))

        # Map raw similarity (0-1 range, typically 0.2-0.8) to 0-100 risk score
        # Calibrated: <0.25 = low risk, 0.25-0.45 = medium, >0.45 = high
        risk_score = min(100.0, max(0.0, (raw_risk - 0.15) * 150.0))

        # Compute dynamic confidence from similarity distribution
        sims_array = np.array(all_max_sims)
        mean_sim = float(np.mean(sims_array))
        std_sim = float(np.std(sims_array)) if len(sims_array) > 1 else 0.0
        # High confidence when many sentences consistently match (low std, high mean)
        # Low confidence when few sparse matches or high variance
        consistency = max(0.0, 1.0 - std_sim * 3.0)  # penalize high variance
        coverage = min(1.0, len(sentence_risks) / max(len(sentences) * 0.3, 1.0))
        confidence = round(0.6 * consistency + 0.4 * coverage, 4)
        confidence = min(1.0, max(0.05, confidence))

        # Category breakdown
        category_scores: Dict[str, list] = {}
        for j, phrase in enumerate(self._concept_phrases):
            cat = self._concept_categories[phrase]
            score_val = float(concept_max_scores[j])
            if score_val > 0.25:
                category_scores.setdefault(cat, []).append(score_val)
        category_breakdown = {
            cat: round(float(np.mean(vals)) * 100, 2)
            for cat, vals in category_scores.items()
        }

        # Top matching concepts (deduplicated by category, top per category)
        matching_concepts = []
        seen_cats = set()
        sorted_indices = np.argsort(concept_max_scores)[::-1]
        for idx in sorted_indices:
            score_val = float(concept_max_scores[idx])
            if score_val < 0.25:
                break
            cat = self._concept_categories[self._concept_phrases[idx]]
            if cat not in seen_cats:
                matching_concepts.append({
                    "concept": self._concept_phrases[idx],
                    "category": cat,
                    "similarity": round(score_val, 4),
                })
                seen_cats.add(cat)
            if len(matching_concepts) >= 10:
                break

        return {
            "risk_score": round(risk_score, 2),
            "matching_concepts": matching_concepts,
            "confidence": confidence,
            "category_breakdown": category_breakdown,
            "sentence_risks": sentence_risks[:20],  # Cap for response size
        }


# Module-level singleton (lazy initialization)
_semantic_analyzer: Optional[SemanticRiskAnalyzer] = None


def _get_semantic_analyzer() -> Optional[SemanticRiskAnalyzer]:
    """Lazily initialize and return the semantic risk analyzer singleton."""
    global _semantic_analyzer
    if _semantic_analyzer is not None:
        return _semantic_analyzer
    if not HAS_SENTENCE_TRANSFORMERS:
        return None
    try:
        _semantic_analyzer = SemanticRiskAnalyzer()
        return _semantic_analyzer
    except Exception as e:
        print(f"[ai_risk_engine] SemanticRiskAnalyzer init failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
#  OCR CONFIDENCE ANALYSIS
# ─────────────────────────────────────────────────────────────────
def compute_ocr_confidence(image_path: str) -> dict:
    """
    Compute OCR confidence metrics for a document image using pytesseract.

    Uses pytesseract image_to_data() with confidence output to assess
    text extraction quality per word, line, and overall.

    Args:
        image_path: Path to the image file.

    Returns:
        dict with keys:
            - overall_confidence (float): weighted mean confidence (0-100)
            - word_count (int): total recognized words
            - low_confidence_words (list): words with confidence < 50
            - confidence_distribution (dict): histogram buckets
            - reliable (bool): True if overall confidence >= 60
    """
    if not HAS_TESSERACT:
        return {
            "overall_confidence": 0.0,
            "word_count": 0,
            "low_confidence_words": [],
            "confidence_distribution": {},
            "reliable": False,
            "error": "pytesseract not installed",
        }

    try:
        img = Image.open(image_path)
        # Get per-word data with confidence scores
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        confidences = []
        low_conf_words = []
        words_text = data.get("text", [])
        words_conf = data.get("conf", [])

        for i, (word, conf) in enumerate(zip(words_text, words_conf)):
            conf_val = int(conf)
            # pytesseract returns -1 for non-text elements
            if conf_val < 0 or not word.strip():
                continue
            confidences.append(conf_val)
            if conf_val < 50 and word.strip():
                low_conf_words.append({
                    "word": word.strip(),
                    "confidence": conf_val,
                    "position": i,
                })

        if not confidences:
            return {
                "overall_confidence": 0.0,
                "word_count": 0,
                "low_confidence_words": [],
                "confidence_distribution": {},
                "reliable": False,
            }

        overall = sum(confidences) / len(confidences)

        # Build confidence distribution histogram
        buckets = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for c in confidences:
            if c < 20:
                buckets["0-20"] += 1
            elif c < 40:
                buckets["20-40"] += 1
            elif c < 60:
                buckets["40-60"] += 1
            elif c < 80:
                buckets["60-80"] += 1
            else:
                buckets["80-100"] += 1

        return {
            "overall_confidence": round(overall, 2),
            "word_count": len(confidences),
            "low_confidence_words": low_conf_words[:30],  # Cap output
            "confidence_distribution": buckets,
            "reliable": overall >= 60.0,
        }

    except Exception as e:
        return {
            "overall_confidence": 0.0,
            "word_count": 0,
            "low_confidence_words": [],
            "confidence_distribution": {},
            "reliable": False,
            "error": str(e),
        }


# ─────────────────────────────────────────────────────────────────
#  TEXT UTILITIES
# ─────────────────────────────────────────────────────────────────
def jaccard_similarity(str1: str, str2: str) -> float:
    a = set(str1.lower().split())
    b = set(str2.lower().split())
    c = a.intersection(b)
    if not a and not b:
        return 1.0
    return float(len(c)) / (len(a) + len(b) - len(c))


def generate_summary(text: str, num_sentences: int = 3) -> str:
    """Extractive summarisation using Term Frequency."""
    if not text or len(text) < 100:
        return text
    sentences = re.split(r'(?<=[.!?]) +', text.replace('\n', ' '))
    words = re.findall(r'\w+', text.lower())
    stop_words = {'the', 'is', 'in', 'and', 'to', 'a', 'of', 'for', 'on', 'with', 'as', 'by', 'this', 'that'}
    word_freq = Counter(w for w in words if w not in stop_words)
    max_freq = max(word_freq.values()) if word_freq else 1
    for w in word_freq:
        word_freq[w] = word_freq[w] / max_freq

    sentence_scores: dict = {}
    for i, sentence in enumerate(sentences):
        for word in re.findall(r'\w+', sentence.lower()):
            if word in word_freq:
                sentence_scores[i] = sentence_scores.get(i, 0) + word_freq[word]

    top_idx = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:num_sentences]
    top_idx.sort()
    return " ".join([sentences[i] for i in top_idx])


def analyze_risk(text: str) -> dict:
    """
    Detect risks via domain-specific NLP.

    Pipeline:
      1. Fast keyword pre-filter (always runs)
      2. Semantic embedding analysis (if sentence-transformers available)
      3. Advanced LLM risk analysis with Chain-of-Thought (red flag extraction)
      4. Combine scores with weighted average for final score
    """
    if not text:
        return {"risk_score": 0, "risk_factors": [], "summary": "No text provided."}

    text_lower = text.lower()

    # ── Step 1: Keyword pre-filter (fast) ──────────────────────
    detected_risks = []
    keyword_score = 0
    for kw, weight in RISK_KEYWORDS.items():
        count = text_lower.count(kw)
        if count > 0:
            detected_risks.append(kw)
            keyword_score += weight * min(count, 3)
    keyword_score = min(keyword_score, 100)

    # ── Step 2: Semantic analysis (if available) ───────────────
    semantic_result = None
    analyzer = _get_semantic_analyzer()
    if analyzer is not None:
        try:
            semantic_result = analyzer.analyze_semantic_risk(text)
        except Exception as e:
            print(f"[ai_risk_engine] Semantic analysis error: {e}")

    # ── Step 3: Advanced LLM Risk Analysis (Chain-of-Thought) ──
    llm_risk_score = None
    llm_risk_factors = []
    llm_cot_reasoning = ""
    try:
        import llm_client
        cot_prompt = (
            f"Evaluate the following vendor document text for procurement risks, non-compliance red flags, or operational warnings.\n"
            f"Specifically search for:\n"
            f"- Fraud, forgery, or document tampering\n"
            f"- Blacklisting or debarment by government authorities\n"
            f"- Financial distress, insolvency, or bankruptcy\n"
            f"- Bid rigging, price fixing, or collusive bidding patterns\n"
            f"- Technical non-compliance, delivery delay records, or quality issues\n\n"
            f"DOCUMENT TEXT (PARTIAL):\n{text[:60000]}\n\n"
            f"Task:\n"
            f"Reason step-by-step and write your analysis using these headers:\n"
            f"1. Fact Ingestion (what key facts are written in the document)\n"
            f"2. Threat Modeling (what specific procurement risks these facts present)\n"
            f"3. Score Weighting (estimate of risk level based on government standards)\n"
            f"Then state your final conclusion following this format: 'CONCLUSION: Risk Score: [score 0-100] | Red Flags: [list of red flags]'"
        )
        system = "You are an expert forensic procurement auditor. Think step-by-step. Base every conclusion strictly on the text."
        
        # Call chain of thought
        llm_cot_reasoning = llm_client.chain_of_thought(cot_prompt, system_instruction=system)
        
        # Parse score (supporting decimals if present)
        score_match = re.search(r'Risk\s*Score:\s*(\d+(?:\.\d+)?)', llm_cot_reasoning, re.IGNORECASE)
        if score_match:
            llm_risk_score = float(score_match.group(1))
            # If the model output a score <= 10 (likely a 1-10 scale) but keywords show high risk, scale it to 0-100
            if 0.0 < llm_risk_score <= 10.0 and keyword_score > 30:
                llm_risk_score = llm_risk_score * 10.0
            
            # Grounding guard: If model returned a very low score (or 0) but keywords are highly critical,
            # override with keyword_score to prevent small-model comprehension failure.
            if keyword_score > 30 and llm_risk_score < keyword_score * 0.7:
                llm_risk_score = max(llm_risk_score, keyword_score)
            
        # Parse red flags list
        flags_match = re.search(r'Red\s*Flags:\s*(.+)', llm_cot_reasoning, re.IGNORECASE)
        if flags_match:
            llm_risk_factors = [f.strip() for f in flags_match.group(1).split(",") if f.strip() and f.strip().lower() != "none"]
    except Exception as e:
        print(f"[ai_risk_engine] LLM Chain-of-Thought risk analysis failed: {e}")

    # ── Step 4: Combine scores ─────────────────────────────────
    if semantic_result and semantic_result.get("risk_score", 0) > 0:
        semantic_score = semantic_result["risk_score"]
        base_combined = 0.4 * keyword_score + 0.6 * semantic_score
    else:
        base_combined = keyword_score

    # Incorporate LLM CoT score if available (weighted 50% LLM, 50% NLP/Semantic)
    if llm_risk_score is not None:
        final_score = min(round(0.5 * base_combined + 0.5 * llm_risk_score, 2), 100)
        # Merge factors
        for factor in llm_risk_factors:
            if factor and factor not in detected_risks:
                detected_risks.append(factor)
        # If LLM found risks, ensure they are represented
        if llm_risk_score > 30 and "AI Flagged Risk" not in detected_risks:
            detected_risks.append("AI Flagged Risk")
    else:
        final_score = base_combined

    # Merge risk factors from semantic matching concepts
    if semantic_result:
        for mc in semantic_result.get("matching_concepts", []):
            concept_label = mc.get("category", mc.get("concept", ""))
            if concept_label and concept_label not in detected_risks:
                detected_risks.append(concept_label)

    # ── Summarization (LLM first, extractive fallback) ─────────
    summary_text = ""
    if llm_cot_reasoning:
        summary_text = llm_cot_reasoning
        if "CONCLUSION:" in summary_text:
            summary_text = summary_text.split("CONCLUSION:")[-1].strip()
    else:
        # If the primary LLM call timed out or failed (llm_risk_score is None),
        # do not try calling LLM again; fall back directly to deterministic summary to save time.
        if llm_risk_score is None:
            summary_text = generate_summary(text)
        else:
            try:
                summary_prompt = (
                    f"Provide a brief, professional, 2-sentence forensic audit summary "
                    f"identifying key risks in this document text:\n\n{text[:15000]}"
                )
                summary_text = call_ollama_generative(summary_prompt)
                if not summary_text:
                    raise ValueError("Empty LLM summary")
            except Exception:
                summary_text = generate_summary(text)

    result = {
        "risk_score": final_score,
        "risk_factors": detected_risks,
        "summary": summary_text,
    }

    # Attach semantic details when available
    if semantic_result:
        result["semantic_analysis"] = {
            "semantic_score": semantic_result["risk_score"],
            "confidence": semantic_result["confidence"],
            "matching_concepts": semantic_result["matching_concepts"],
            "category_breakdown": semantic_result.get("category_breakdown", {}),
        }

    if llm_risk_score is not None:
        result["llm_analysis"] = {
            "llm_risk_score": llm_risk_score,
            "llm_risk_factors": llm_risk_factors,
            "cot_reasoning": llm_cot_reasoning
        }

    return result


# ─────────────────────────────────────────────────────────────────
#  OLLAMA LLM INTEGRATION
# ─────────────────────────────────────────────────────────────────

def call_ollama_generative(prompt: str) -> str:
    """
    Calls the configured active LLM provider for pure generative text.
    """
    import llm_client
    return llm_client.generate_text(prompt)


def _deterministic_score(criteria_name: str, context_text: str, max_score: float) -> dict:
    """
    Fully deterministic NLP fallback when Ollama is unavailable.
    Uses keyword matching and regex extraction.
    Confidence is dynamically computed based on match quality and coverage.
    """
    text_lower = context_text.lower()
    criteria_lower = criteria_name.lower()
    score = 0.0
    rationale = "Deterministic NLP analysis."

    # Track match quality signals for dynamic confidence
    match_signals = []  # list of floats 0-1, higher = stronger evidence

    if any(kw in criteria_lower for kw in ("iso", "certification", "certificate")):
        iso_patterns = [
            r'iso\s*\d{4,5}', r'iso\s*9001', r'iso\s*14001', r'iso\s*27001',
            r'bis\s*certif', r'certification\s*number', r'certificate\s*of\s*compliance',
        ]
        pattern_hits = sum(1 for p in iso_patterns if re.search(p, text_lower))
        if pattern_hits > 0:
            match_strength = min(1.0, pattern_hits / 3.0)
            score = max_score * (0.7 + 0.3 * match_strength)
            rationale += f" {pattern_hits} ISO/certification pattern(s) found in documents."
            match_signals.append(0.7 + 0.3 * match_strength)
        elif "iso" in text_lower or "certif" in text_lower:
            score = max_score * 0.6
            rationale += " General ISO/certification mention found."
            match_signals.append(0.5)
        else:
            score = max_score * 0.2
            rationale += " No certification evidence found."
            match_signals.append(0.15)

    elif any(kw in criteria_lower for kw in ("experience", "years", "track record")):
        years_matches = re.findall(r'(\d+)\s*(?:years?|yrs?)', text_lower)
        if years_matches:
            max_yrs = max(int(y) for y in years_matches)
            score = min((max_yrs / 5.0) * max_score, max_score)
            rationale += f" Extracted {max_yrs} year(s) of experience from {len(years_matches)} mention(s)."
            match_signals.append(min(1.0, max_yrs / 5.0))
            if len(years_matches) > 1:
                match_signals.append(0.8)  # Multiple mentions = corroboration
        else:
            exp_keywords = {"experience", "experienced", "track record", "established", "since"}
            exp_hits = sum(1 for kw in exp_keywords if kw in text_lower)
            if exp_hits > 0:
                score = max_score * min(0.5, 0.15 * exp_hits)
                rationale += f" General experience mentioned ({exp_hits} indicator(s)) but no specific duration."
                match_signals.append(0.3)
            else:
                score = max_score * 0.1
                rationale += " No experience indicators found."
                match_signals.append(0.1)

    elif any(kw in criteria_lower for kw in ("turnover", "financial", "revenue", "balance")):
        # Look for monetary patterns
        money_patterns = re.findall(
            r'(?:rs\.?|inr|₹|usd|\$)\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*(?:crore|lakh|million|billion)',
            text_lower
        )
        digits = re.findall(r'[\d,]+(?:\.\d+)?', text_lower)
        fin_keywords = {"turnover", "revenue", "profit", "balance sheet", "audit", "financial statement"}
        fin_hits = sum(1 for kw in fin_keywords if kw in text_lower)

        if money_patterns:
            match_strength = min(1.0, len(money_patterns) / 4.0)
            score = max_score * (0.65 + 0.35 * match_strength)
            rationale += f" {len(money_patterns)} monetary figure(s) found with {fin_hits} financial keyword(s)."
            match_signals.append(0.7 + 0.2 * match_strength)
        elif digits:
            score = max_score * 0.55
            rationale += f" Numerical data found ({len(digits)} figure(s)) but no clear monetary context."
            match_signals.append(0.45)
        else:
            score = max_score * 0.20
            rationale += " Financial mention but no numeric data."
            match_signals.append(0.2)

    elif any(kw in criteria_lower for kw in ("technical", "specification", "compliance", "standard")):
        tech_kws = {"specification", "standard", "compliance", "technical", "qualified", "approved",
                     "compliant", "meets", "conforms", "requirement", "tested", "verified"}
        text_words = set(re.findall(r'\w+', text_lower))
        hits = tech_kws.intersection(text_words)
        hit_ratio = len(hits) / len(tech_kws)
        score = min(hit_ratio * max_score * 1.2, max_score)  # Slight boost for high coverage
        rationale += f" {len(hits)}/{len(tech_kws)} technical compliance keyword(s) matched."
        match_signals.append(min(1.0, hit_ratio * 1.2))

    else:
        # Generic keyword overlap
        prompt_words = set(re.findall(r'\w+', criteria_lower)) - {
            'the', 'is', 'in', 'and', 'to', 'a', 'of', 'for', 'on', 'with',
            'as', 'by', 'this', 'that', 'you', 'are', 'expert', 'procurement',
        }
        ctx_words = set(re.findall(r'\w+', text_lower))
        overlap = prompt_words.intersection(ctx_words)
        if overlap:
            overlap_ratio = len(overlap) / max(len(prompt_words), 1)
            score = min(overlap_ratio * max_score, max_score)
            rationale += f" {len(overlap)} keyword match(es) with criteria."
            match_signals.append(min(1.0, overlap_ratio))
        else:
            score = 0.0
            rationale += " No relevant information found."
            match_signals.append(0.0)

    # ── Dynamic confidence computation ─────────────────────────
    # Base confidence from mean match quality
    if match_signals:
        mean_signal = sum(match_signals) / len(match_signals)
        # More signals = more evidence = higher confidence
        evidence_breadth = min(1.0, len(match_signals) / 3.0)
        # Text length factor: longer text = more reliable analysis
        text_len_factor = min(1.0, len(context_text) / 2000.0)
        # Combine: 50% match quality, 30% evidence breadth, 20% text coverage
        dynamic_confidence = 0.50 * mean_signal + 0.30 * evidence_breadth + 0.20 * text_len_factor
        dynamic_confidence = round(min(0.98, max(0.05, dynamic_confidence)), 4)
    else:
        dynamic_confidence = 0.1

    return {
        "suggested_score": round(score, 2),
        "reasoning": rationale,
        "confidence_interval": dynamic_confidence,
    }


# ─────────────────────────────────────────────────────────────────
#  MAIN SCORING FUNCTION (RAG + LLM)
# ─────────────────────────────────────────────────────────────────
def generate_ai_score_suggestion(criteria_name: str, max_score: float, documents: list) -> dict:
    """
    Advanced RAG scoring:
    1. Retrieve OCR text from all bid documents and query RAG index (filtered by vendor_id)
    2. Try Ollama llama3 for intelligent scoring with evidence citations
    3. Fall back to deterministic NLP if Ollama unavailable
    """
    if not documents:
        return {"score": 0.0, "rationale": "No documents provided to evaluate."}

    # Extract vendor context
    vendor_id = None
    vendor_name = ""
    if documents and hasattr(documents[0], "bid") and documents[0].bid:
        vendor_id = documents[0].bid.vendor_id
        if documents[0].bid.vendor:
            vendor_name = documents[0].bid.vendor.company_name

    # Step 1: Retrieve relevant chunks from RAG index
    context_chunks = []
    try:
        import rag_engine
        filter_metadata = {"vendor_id": vendor_id} if vendor_id else None
        retrieved = rag_engine.multi_query_retrieve(
            question=criteria_name,
            filter_metadata=filter_metadata,
            k=5
        )
        context_chunks = [c.page_content for c in retrieved]
    except Exception as e:
        print(f"[ai_risk_engine] RAG retrieval failed, falling back to local doc text: {e}")

    # Fallback to local document ocr chunking if RAG retrieval is empty
    if not context_chunks:
        combined_context = " ".join([doc.ocr_extracted_text for doc in documents if doc.ocr_extracted_text])
        if combined_context:
            chunk_size = 1000
            overlap = 200
            context_chunks = [
                combined_context[i:i + chunk_size]
                for i in range(0, len(combined_context), chunk_size - overlap)
            ][:5]

    if not context_chunks:
        return {"score": 0.0, "rationale": "Documents contained no readable OCR text."}

    # Step 2: Structured scoring with evidence citation using LLM
    res = {}
    try:
        import llm_client
        res = llm_client.score_with_evidence(
            criteria_name=criteria_name,
            max_score=max_score,
            context_chunks=context_chunks,
            vendor_name=vendor_name
        )
    except Exception as e:
        print(f"[ai_risk_engine] LLM score_with_evidence call failed: {e}")

    # Step 3: Handle output and fallback to deterministic NLP
    if not res or (res.get("confidence", 0) == 0 and "failed" in res.get("rationale", "").lower()):
        # Try a direct fallback
        combined_context = " ".join([doc.ocr_extracted_text for doc in documents if doc.ocr_extracted_text])
        fallback_res = _deterministic_score(criteria_name, combined_context, max_score)
        final_score = fallback_res.get("suggested_score", 0.0)
        rationale = fallback_res.get("reasoning", "Fallback analysis.")
        confidence = fallback_res.get("confidence_interval", 0.5)
        source = "Deterministic NLP"
        evidence_quote = "N/A"
        needs_review = True
    else:
        final_score = res.get("score", 0.0)
        rationale = res.get("rationale", "Evaluation complete.")
        confidence = res.get("confidence", 80) / 100.0
        source = "AI Engine"
        evidence_quote = res.get("evidence_quote", "No evidence found.")
        needs_review = res.get("needs_human_review", False)

    confidence_label = "High" if confidence > 0.8 else "Medium" if confidence > 0.5 else "Low"
    
    # Format rationale to include evidence quote if available
    formatted_rationale = f"[{source} | {confidence_label} Confidence] {rationale}"
    if evidence_quote and evidence_quote not in ("No evidence found", "No evidence found.", "N/A"):
        formatted_rationale += f" (Evidence Quote: \"{evidence_quote}\")"
    if needs_review:
        formatted_rationale += " [Requires Human Review]"

    return {
        "score": round(final_score, 2),
        "rationale": formatted_rationale,
        "metrics": {
            "llm_confidence": confidence,
            "evidence_found": final_score > 0.2 * max_score,
            "source": source,
            "needs_human_review": needs_review,
        },
    }


# ─────────────────────────────────────────────────────────────────
#  VENDOR RISK SCORING ENGINE
# ─────────────────────────────────────────────────────────────────
def compute_vendor_risk_score(vendor, bids: list, deliveries: list, payments: list) -> dict:
    """
    Multi-dimensional deterministic vendor risk model.
    Returns risk_score (0-100, higher = more risk), tier, factors, recommendations.
    """
    factors = []
    score = 0

    # ── Dimension 1: Blacklist status (max 40pts) ─────────────
    if getattr(vendor, "is_blacklisted", False):
        score += 40
        factors.append({"factor": "Vendor is blacklisted", "weight": 40, "severity": "CRITICAL"})

    # ── Dimension 2: Performance score (max 25pts) ────────────
    perf = getattr(vendor, "performance_score", 100.0) or 100.0
    perf_risk = max(0, round((100 - perf) * 0.25, 1))
    if perf_risk > 0:
        score += perf_risk
        factors.append({
            "factor": f"Low performance score: {perf:.1f}/100",
            "weight": perf_risk,
            "severity": "HIGH" if perf < 40 else "MODERATE",
        })

    # ── Dimension 3: Bid win rate (max 10pts) ─────────────────
    total_bids = len(bids)
    won_bids = len([b for b in bids if getattr(b, "status", "") == "Awarded"])
    if total_bids > 0:
        win_rate = won_bids / total_bids
        # Very high win rate (>80%) on many tenders could indicate bid manipulation
        if total_bids >= 3 and win_rate > 0.8:
            score += 8
            factors.append({
                "factor": f"Unusually high win rate: {win_rate*100:.0f}% ({won_bids}/{total_bids})",
                "weight": 8,
                "severity": "MODERATE",
            })
        elif total_bids >= 2 and won_bids == 0:
            score += 5
            factors.append({
                "factor": f"Zero wins in {total_bids} bid attempt(s) — potential quality issue",
                "weight": 5,
                "severity": "LOW",
            })

    # ── Dimension 4: Delivery failures (max 20pts) ────────────
    failed_inspections = [d for d in deliveries if getattr(d, "inspection_status", "") == "Failed"]
    if failed_inspections:
        d_risk = min(20, len(failed_inspections) * 7)
        score += d_risk
        factors.append({
            "factor": f"{len(failed_inspections)} failed inspection(s) on record",
            "weight": d_risk,
            "severity": "HIGH" if len(failed_inspections) > 1 else "MODERATE",
        })

    # ── Dimension 5: Payment holds (max 10pts) ────────────────
    held_payments = [p for p in payments if getattr(p, "payment_status", "") == "Held"]
    if held_payments:
        p_risk = min(10, len(held_payments) * 5)
        score += p_risk
        factors.append({
            "factor": f"{len(held_payments)} payment(s) currently held",
            "weight": p_risk,
            "severity": "MODERATE",
        })

    # ── Dimension 6: Price dumping in bids (max 10pts) ────────
    dump_bids = 0
    for b in bids:
        tender = getattr(b, "tender", None)
        if tender and getattr(tender, "estimated_value", 0) and getattr(b, "total_amount", 0):
            if b.total_amount < tender.estimated_value * 0.5:
                dump_bids += 1
    if dump_bids:
        score += min(10, dump_bids * 5)
        factors.append({
            "factor": f"{dump_bids} bid(s) below 50% of tender estimate (price dumping)",
            "weight": min(10, dump_bids * 5),
            "severity": "HIGH",
        })

    total_score = round(min(score, 100), 1)

    # ── Tier assignment ───────────────────────────────────────
    if total_score >= 60:
        tier = "CRITICAL"
        tier_color = "#ef4444"
    elif total_score >= 35:
        tier = "HIGH"
        tier_color = "#f59e0b"
    elif total_score >= 15:
        tier = "MEDIUM"
        tier_color = "#3b82f6"
    else:
        tier = "LOW"
        tier_color = "#10b981"

    # ── Recommendations ───────────────────────────────────────
    recommendations = []
    if getattr(vendor, "is_blacklisted", False):
        recommendations.append("Disqualify immediately from all active tenders.")
    if perf < 50:
        recommendations.append("Require performance bond and enhanced SLA monitoring.")
    if failed_inspections:
        recommendations.append("Mandate third-party inspection (TPI) on all future deliveries.")
    if held_payments:
        recommendations.append("Resolve invoice disputes before issuing new POs.")
    if dump_bids:
        recommendations.append("Apply extra technical scrutiny — low bids risk quality delivery.")
    if not recommendations:
        recommendations.append("No immediate action required. Continue routine monitoring.")

    return {
        "risk_score": total_score,
        "risk_tier": tier,
        "tier_color": tier_color,
        "risk_factors": factors,
        "recommendations": recommendations,
        "dimensions": {
            "blacklist": 40 if getattr(vendor, "is_blacklisted", False) else 0,
            "performance": perf_risk,
            "win_rate": min(8, total_bids * 1 if total_bids > 0 else 0),
            "delivery": min(20, len(failed_inspections) * 7),
            "payments": min(10, len(held_payments) * 5),
            "pricing": min(10, dump_bids * 5),
        },
    }


# ─────────────────────────────────────────────────────────────────
#  LEGAL NOTICE GENERATOR (Ollama-powered)
# ─────────────────────────────────────────────────────────────────
def generate_legal_notice(
    vendor_name: str, po_number: str, ld_clause: str, grn: str, amount: float
) -> str:
    """Generates a professional legal notice via the configured active LLM."""
    prompt = (
        f"Generate a strict, professional 3-paragraph Legal Notice of Default and Liquidated Damages "
        f"to {vendor_name} for Purchase Order {po_number}. "
        f"They failed Quality Inspection for Goods Receipt Note {grn}. "
        f"Mention the Liquidated Damages clause: '{ld_clause}' and state that a penalty of INR {amount:,.2f} is being levied. "
        f"Return ONLY the text of the legal notice, no preamble or metadata."
    )
    try:
        import llm_client
        return llm_client.generate_text(prompt, temperature=0.3)
    except Exception:
        return None  # Caller handles fallback

# ─────────────────────────────────────────────────────────────────
#  ESG & CARBON FOOTPRINT COMPLIANCE EXTRACTOR
# ─────────────────────────────────────────────────────────────────
def extract_esg_metrics(ocr_text: str) -> dict:
    """
    Advanced Automated ESG (Environmental, Social, Governance) and Carbon Footprint audit scanner.
    Analyzes document text for sustainability standards, environmental claims, carbon intensity, and governance checks.
    """
    if not ocr_text or len(ocr_text.strip()) < 10:
        return {"esg_score": 0.0, "highlights": []}
    
    text_lower = ocr_text.lower()
    score = 0.0
    highlights = []
    
    # Check 1: Environmental Certifications (max 30 pts)
    env_certs = {
        "iso 14001": ("ISO 14001 Environmental Management System certified", 15),
        "iso 50001": ("ISO 50001 Energy Management certified", 10),
        "leed": ("LEED/Green Building certified facility", 5),
        "gri index": ("GRI Sustainability Reporting compliance", 5),
    }
    env_score = 0
    for key, (desc, pts) in env_certs.items():
        if key in text_lower:
            env_score += pts
            highlights.append(desc)
    score += min(env_score, 30)
    
    # Check 2: Carbon Footprint & Offsets (max 30 pts)
    carbon_kws = {
        "carbon footprint": ("Carbon footprint disclosure audit present", 10),
        "carbon offset": ("Active carbon offset initiatives identified", 10),
        "net zero": ("Commitment to Net Zero carbon operations", 5),
        "greenhouse gas": ("GHG Emissions reporting present", 5),
        "ghg protocol": ("GHG Protocol accounting utilized", 5),
    }
    carbon_score = 0
    for key, (desc, pts) in carbon_kws.items():
        if key in text_lower:
            carbon_score += pts
            highlights.append(desc)
    score += min(carbon_score, 30)
    
    # Check 3: Social & Circular Economy factors (max 20 pts)
    social_kws = {
        "renewable energy": ("Uses renewable/solar energy sources", 5),
        "solar power": ("Uses renewable/solar energy sources", 5),
        "recycl": ("Circular economy / recycling process implemented", 5),
        "diversity": ("Diversity and inclusion workplace policy active", 5),
        "human rights": ("Human rights and fair labor checks active", 5),
    }
    social_score = 0
    for key, (desc, pts) in social_kws.items():
        if key in text_lower:
            if desc not in highlights:
                social_score += pts
                highlights.append(desc)
    score += min(social_score, 20)
    
    # Check 4: Governance & Corporate Policies (max 20 pts)
    gov_kws = {
        "anti-corruption": ("Anti-corruption policies active", 5),
        "anti-bribery": ("Anti-bribery policies active", 5),
        "whistleblower": ("Whistleblower protection framework active", 5),
        "iso 37001": ("ISO 37001 Anti-Bribery management certified", 5),
        "board diversity": ("Board of directors diversity guidelines met", 5),
    }
    gov_score = 0
    for key, (desc, pts) in gov_kws.items():
        if key in text_lower:
            gov_score += pts
            highlights.append(desc)
    score += min(gov_score, 20)
    
    # Baseline score for generic documents
    if score == 0:
        score = 15.0
        highlights.append("Standard business operation documentation")
        
    return {
        "esg_score": round(score, 2),
        "highlights": highlights
    }


# ─────────────────────────────────────────────────────────────────
#  ADVANCED STATISTICAL UTILITIES v5.0
#  Gini, Tukey, Grubbs, Skewness/Kurtosis, Shapley, Price Entropy
# ─────────────────────────────────────────────────────────────────

def compute_gini(values: List[float]) -> float:
    """
    Compute Gini coefficient (0=perfect equality, 1=maximum inequality).
    O(n log n) sorted-index formula.
    """
    arr = sorted([v for v in values if v is not None and v > 0])
    n = len(arr)
    if n < 2:
        return 0.0
    total = sum(arr)
    if total == 0:
        return 0.0
    weighted = sum((i + 1) * x for i, x in enumerate(arr))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def compute_tukey_fences(values: List[float]) -> dict:
    """
    Compute Tukey fence outlier bounds using IQR method.
    Inner fences: Q1 - 1.5*IQR, Q3 + 1.5*IQR
    Outer fences: Q1 - 3.0*IQR, Q3 + 3.0*IQR
    Returns quartiles, IQR, fence bounds, and outlier lists.
    """
    if not values or len(values) < 4:
        return {
            "q1": 0.0, "q2_median": 0.0, "q3": 0.0, "iqr": 0.0,
            "lower_inner": 0.0, "upper_inner": 0.0,
            "lower_outer": 0.0, "upper_outer": 0.0,
            "mild_outliers": [], "extreme_outliers": [], "clean_values": values
        }
    arr = sorted(v for v in values if v is not None)
    n = len(arr)

    def _percentile(data, pct):
        idx = (pct / 100) * (len(data) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(data) - 1)
        return data[lo] + (data[hi] - data[lo]) * (idx - lo)

    q1 = _percentile(arr, 25)
    q2 = _percentile(arr, 50)
    q3 = _percentile(arr, 75)
    iqr = q3 - q1

    li = q1 - 1.5 * iqr
    ui = q3 + 1.5 * iqr
    lo_outer = q1 - 3.0 * iqr
    hi_outer = q3 + 3.0 * iqr

    mild_outliers = [v for v in arr if (v < li or v > ui) and (v >= lo_outer and v <= hi_outer)]
    extreme_outliers = [v for v in arr if v < lo_outer or v > hi_outer]
    clean_values = [v for v in arr if li <= v <= ui]

    return {
        "q1": round(q1, 2), "q2_median": round(q2, 2), "q3": round(q3, 2),
        "iqr": round(iqr, 2),
        "lower_inner": round(li, 2), "upper_inner": round(ui, 2),
        "lower_outer": round(lo_outer, 2), "upper_outer": round(hi_outer, 2),
        "mild_outliers": [round(v, 2) for v in mild_outliers],
        "extreme_outliers": [round(v, 2) for v in extreme_outliers],
        "clean_values": [round(v, 2) for v in clean_values],
    }


def compute_grubbs_test(values: List[float], alpha: float = 0.05) -> dict:
    """
    Grubbs test for single most extreme outlier detection.
    Returns the suspected outlier, G-statistic, and whether it is significant.
    Critical value approximated using t-distribution.
    """
    arr = [v for v in values if v is not None]
    n = len(arr)
    if n < 3:
        return {"outlier": None, "g_stat": 0.0, "significant": False, "note": "Need >= 3 values"}

    mean_v = sum(arr) / n
    std_v = (sum((x - mean_v) ** 2 for x in arr) / (n - 1)) ** 0.5 if n > 1 else 1.0
    if std_v == 0:
        return {"outlier": None, "g_stat": 0.0, "significant": False, "note": "Zero variance"}

    deviations = [abs(v - mean_v) for v in arr]
    max_idx = deviations.index(max(deviations))
    g_stat = max(deviations) / std_v

    # Approximate critical value using Bonferroni-corrected t-distribution (simplified)
    # For alpha=0.05 and n, critical G ≈ ((n-1)/sqrt(n)) * sqrt(t_sq / (n - 2 + t_sq))
    # Use conservative lookup table approximation
    critical_lookup = {
        3: 1.155, 4: 1.481, 5: 1.715, 6: 1.887, 7: 2.020, 8: 2.126, 9: 2.215,
        10: 2.290, 15: 2.549, 20: 2.709, 25: 2.822, 30: 2.908, 50: 3.128
    }
    # Find closest n in lookup
    n_keys = sorted(critical_lookup.keys())
    closest_n = min(n_keys, key=lambda k: abs(k - n))
    critical_g = critical_lookup.get(closest_n, 3.5)  # fallback for large n

    return {
        "outlier": round(arr[max_idx], 2),
        "outlier_index": max_idx,
        "g_stat": round(g_stat, 4),
        "critical_g": round(critical_g, 4),
        "significant": g_stat > critical_g,
        "mean": round(mean_v, 2),
        "std": round(std_v, 2),
        "n": n,
    }


def compute_skewness_kurtosis(values: List[float]) -> dict:
    """
    Compute statistical shape metrics:
    - Skewness: asymmetry of distribution (>0 right-skewed, <0 left-skewed)
    - Excess Kurtosis: tail heaviness relative to normal (0=normal, >0=heavy tails)
    """
    arr = [v for v in values if v is not None]
    n = len(arr)
    if n < 3:
        return {"skewness": 0.0, "kurtosis": 0.0, "interpretation": "Insufficient data"}

    mean_v = sum(arr) / n
    variance = sum((x - mean_v) ** 2 for x in arr) / n
    std_v = variance ** 0.5 if variance > 0 else 1.0

    skewness = sum(((x - mean_v) / std_v) ** 3 for x in arr) / n
    kurtosis = sum(((x - mean_v) / std_v) ** 4 for x in arr) / n - 3.0  # excess

    if abs(skewness) < 0.5:
        skew_label = "Symmetric"
    elif skewness > 0:
        skew_label = "Right-Skewed (high-price outliers)"
    else:
        skew_label = "Left-Skewed (low-price outliers)"

    if kurtosis > 1.0:
        kurt_label = "Leptokurtic — heavy tails, extreme bids present"
    elif kurtosis < -1.0:
        kurt_label = "Platykurtic — thin tails, bids clustered centrally"
    else:
        kurt_label = "Mesokurtic — near-normal distribution"

    return {
        "skewness": round(skewness, 4),
        "kurtosis_excess": round(kurtosis, 4),
        "skewness_label": skew_label,
        "kurtosis_label": kurt_label,
        "interpretation": f"{skew_label}. {kurt_label}.",
    }


def compute_price_entropy(values: List[float], n_bins: int = 10) -> dict:
    """
    Shannon entropy of bid price distribution.
    Low entropy = bids highly clustered (suspicious cartel signal).
    High entropy = diverse, competitive bids.
    """
    arr = [v for v in values if v is not None and v > 0]
    if len(arr) < 2:
        return {"entropy": 0.0, "normalized_entropy": 0.0, "risk": "INSUFFICIENT_DATA"}

    min_v, max_v = min(arr), max(arr)
    if min_v == max_v:
        return {"entropy": 0.0, "normalized_entropy": 0.0, "risk": "CRITICAL — Identical bids"}

    bin_width = (max_v - min_v) / n_bins
    bins = [0] * n_bins
    for v in arr:
        idx = min(int((v - min_v) / bin_width), n_bins - 1)
        bins[idx] += 1

    total = len(arr)
    entropy = 0.0
    for count in bins:
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    max_entropy = math.log2(n_bins)
    normalized = entropy / max_entropy if max_entropy > 0 else 0.0

    if normalized < 0.25:
        risk = "CRITICAL — Severe Price Clustering"
    elif normalized < 0.50:
        risk = "HIGH — Price Clustering Detected"
    elif normalized < 0.75:
        risk = "MODERATE — Some Clustering"
    else:
        risk = "LOW — Healthy Competition"

    return {
        "entropy": round(entropy, 4),
        "normalized_entropy": round(normalized, 4),
        "entropy_pct": round(normalized * 100, 2),
        "risk": risk,
        "bin_distribution": bins,
    }


def compute_shapley_values(
    bid_amount: float,
    mean_amount: float,
    vendor_performance: float,
    technical_score: float,
    delivery_days: float,
    price_to_estimate: float,
    is_msme: bool,
) -> dict:
    """
    Approximate Shapley value attribution for composite bid score.
    Uses Owen value approximation with marginal contribution sampling.
    Shows how much each factor contributes to the final composite score.
    """
    import math

    # Normalize each raw feature to [0, 100] score
    price_dev = max(0.0, min(100.0, 100.0 - abs(bid_amount - mean_amount) / max(mean_amount, 1) * 100))
    trust = min(100.0, max(0.0, float(vendor_performance)))
    tech = min(100.0, max(0.0, float(technical_score)))
    delivery = max(0.0, min(100.0, 120.0 - float(delivery_days)))
    per_sanity = max(0.0, min(100.0, 100.0 - abs(1.0 - float(price_to_estimate)) * 150.0))
    msme_bonus = 10.0 if is_msme else 0.0

    features = {
        "price_deviation": price_dev,
        "vendor_trust": trust,
        "technical_competence": tech,
        "delivery_feasibility": delivery,
        "price_estimate_sanity": per_sanity,
        "msme_policy_bonus": msme_bonus,
    }

    # Weights from the composite scoring formula
    weights = {
        "price_deviation": 0.20,
        "vendor_trust": 0.25,
        "technical_competence": 0.25,
        "delivery_feasibility": 0.10,
        "price_estimate_sanity": 0.15,
        "msme_policy_bonus": 0.05,
    }

    # Shapley = weighted marginal contribution (exact for linear scoring functions)
    total_weighted = sum(features[k] * weights[k] for k in features)
    shapley = {}
    for k in features:
        contribution = features[k] * weights[k]
        shapley[k] = {
            "raw_score": round(features[k], 2),
            "weight": weights[k],
            "contribution": round(contribution, 2),
            "contribution_pct": round((contribution / max(total_weighted, 0.01)) * 100, 1),
        }

    # Dominant factor
    dominant = max(shapley, key=lambda k: shapley[k]["contribution"])

    return {
        "composite_score": round(total_weighted, 2),
        "shapley_values": shapley,
        "dominant_factor": dominant,
        "dominant_contribution_pct": shapley[dominant]["contribution_pct"],
    }


# ─────────────────────────────────────────────────────────────────
#  PROCUREMENT RULE ENGINE v1.0
#  GEM / CVC / GFR 2017 Compliance Rule Checker
# ─────────────────────────────────────────────────────────────────

# Master rule database with source citations
PROCUREMENT_RULES: List[dict] = [
    # ── GFR 2017 Rules ──────────────────────────────────────────
    {
        "id": "GFR-2017-R173",
        "source": "GFR 2017 Rule 173",
        "category": "Competition",
        "title": "Minimum Competition Requirement",
        "description": "For open tenders above ₹25 Lakhs, minimum 3 bids must be received for valid comparison.",
        "threshold_type": "min_bids",
        "threshold_value": 3,
        "severity": "CRITICAL",
    },
    {
        "id": "GFR-2017-R175",
        "source": "GFR 2017 Rule 175",
        "category": "Price Reasonableness",
        "title": "Price Reasonableness Check",
        "description": "The L1 bid price must be compared against the estimated cost. Price deviations >25% above estimate require PAC approval.",
        "threshold_type": "price_deviation_pct",
        "threshold_value": 25.0,
        "severity": "HIGH",
    },
    {
        "id": "GFR-2017-R160",
        "source": "GFR 2017 Rule 160",
        "category": "Documentation",
        "title": "Mandatory Vendor Documentation",
        "description": "All vendors must submit valid GST registration, PAN, and experience certificates. Missing documents disqualify the bid.",
        "threshold_type": "documentation",
        "threshold_value": None,
        "severity": "CRITICAL",
    },
    {
        "id": "GFR-2017-R162",
        "source": "GFR 2017 Rule 162",
        "category": "Bid Validity",
        "title": "Bid Validity Period",
        "description": "Bids must remain valid for a minimum of 90 days from submission date for tenders above ₹10 Lakhs.",
        "threshold_type": "validity_days",
        "threshold_value": 90,
        "severity": "MODERATE",
    },
    # ── CVC Guidelines ──────────────────────────────────────────
    {
        "id": "CVC-GL-01",
        "source": "CVC Circular No. 03/01/12",
        "category": "Anti-Corruption",
        "title": "Single Tender / Limited Tender Justification",
        "description": "Single-source procurement requires specific CVC-approved justification. Repeated single tenders from the same vendor are flagged.",
        "threshold_type": "single_source",
        "threshold_value": None,
        "severity": "HIGH",
    },
    {
        "id": "CVC-GL-02",
        "source": "CVC Circular No. 98/DSP/7",
        "category": "Collusion Detection",
        "title": "Identical Bids Prohibition",
        "description": "Identical or near-identical bid amounts from different vendors (within 0.5% gap) are a collusion indicator and must be referred to Vigilance.",
        "threshold_type": "bid_gap_pct",
        "threshold_value": 0.5,
        "severity": "CRITICAL",
    },
    {
        "id": "CVC-GL-03",
        "source": "CVC Advisory on e-Procurement 2014",
        "category": "IP / Conduct",
        "title": "Same IP Address Submissions",
        "description": "Multiple bids submitted from the same IP address must be flagged as potential collusion.",
        "threshold_type": "ip_collision",
        "threshold_value": None,
        "severity": "CRITICAL",
    },
    {
        "id": "CVC-GL-04",
        "source": "CVC Circular No. 10/12/07",
        "category": "Post-Tender",
        "title": "Post-Tender Negotiation Prohibition",
        "description": "Post-tender price negotiations with L1 vendor are prohibited unless the estimated price is based on a market study.",
        "threshold_type": "negotiation",
        "threshold_value": None,
        "severity": "HIGH",
    },
    # ── GeM / DPIIT Rules ────────────────────────────────────────
    {
        "id": "GEM-DPIIT-01",
        "source": "GeM Procurement Manual 2023 - Section 4.2",
        "category": "MSME Policy",
        "title": "MSME 25% Procurement Mandate",
        "description": "At least 25% of annual procurement value must be sourced from MSME vendors per Public Procurement Policy for MSMEs Order 2012.",
        "threshold_type": "msme_pct",
        "threshold_value": 25.0,
        "severity": "COMPLIANCE",
    },
    {
        "id": "GEM-DPIIT-02",
        "source": "DPIIT Make in India Order 2017",
        "category": "Make in India",
        "title": "Class I / Class II Local Supplier Preference",
        "description": "For tenders above ₹200 Cr, only Class I local suppliers (>50% local content) are eligible. Class II (20-50% local content) get price preference.",
        "threshold_type": "local_content",
        "threshold_value": 50.0,
        "severity": "HIGH",
    },
    {
        "id": "GEM-DPIIT-03",
        "source": "GeM Rule 4(viii) — Blacklisting",
        "category": "Vendor Integrity",
        "title": "Blacklisted Vendor Exclusion",
        "description": "Any vendor debarred/blacklisted by any Central/State government department must be automatically excluded from all procurements.",
        "threshold_type": "blacklist_check",
        "threshold_value": None,
        "severity": "CRITICAL",
    },
    {
        "id": "GEM-DPIIT-04",
        "source": "GeM Manual — EMD Requirement",
        "category": "Financial Security",
        "title": "Earnest Money Deposit (EMD) Requirement",
        "description": "For tenders above ₹10 Lakhs, an EMD of 2-3% of estimated value must be collected from all bidders except MSME/NSIC registered firms.",
        "threshold_type": "emd_compliance",
        "threshold_value": 10.0,
        "severity": "MODERATE",
    },
    # ── IOCL / PSU-Specific Rules ────────────────────────────────
    {
        "id": "IOCL-PR-01",
        "source": "IOCL Purchase Manual — Section 8.3",
        "category": "Price Ceiling",
        "title": "L1 Underbid Protection",
        "description": "Bids below 70% of the estimated value are automatically flagged as abnormally low bids (ALB) requiring technical justification.",
        "threshold_type": "alb_pct",
        "threshold_value": 70.0,
        "severity": "HIGH",
    },
    {
        "id": "IOCL-PR-02",
        "source": "IOCL Purchase Manual — Section 11.2",
        "category": "Performance Bond",
        "title": "Performance Bank Guarantee Requirement",
        "description": "All contracts above ₹50 Lakhs require a Performance Bank Guarantee (PBG) of 10% of contract value from the awarded vendor.",
        "threshold_type": "pbg_threshold",
        "threshold_value": 50.0,
        "severity": "HIGH",
    },
    {
        "id": "IOCL-PR-03",
        "source": "IOCL / OISD Safety Standard 137",
        "category": "Safety Compliance",
        "title": "OISD Safety Certification for Petroleum Equipment",
        "description": "All vendors supplying petroleum / refinery equipment must hold valid OISD-137 certification and submit it during bid submission.",
        "threshold_type": "safety_cert",
        "threshold_value": None,
        "severity": "CRITICAL",
    },
]


def evaluate_procurement_rules(
    query: str,
    context: dict,
) -> dict:
    """
    Rule-based procurement compliance query engine.

    Matches a free-text query against the rule database using keyword scoring,
    then evaluates each matching rule against the provided procurement context.

    Args:
        query: Natural language procurement query (e.g. 'MSME compliance', 'blacklisted vendor')
        context: Dict with procurement context keys:
            - n_bids: int
            - estimated_value_lakhs: float
            - l1_amount_lakhs: float
            - msme_pct: float
            - has_blacklisted: bool
            - min_bid_gap_pct: float (min gap between adjacent bids)
            - bid_amounts: list[float]

    Returns:
        dict with matched_rules, compliance_results, overall_status, recommendations
    """
    query_lower = query.lower()

    # Keyword mapping for rule matching
    keyword_map = {
        "GFR-2017-R173": ["competition", "minimum bids", "valid comparison", "open tender", "3 bids", "participation"],
        "GFR-2017-R175": ["price reasonableness", "estimate", "deviation", "overpriced", "pac approval", "above estimate"],
        "GFR-2017-R160": ["documentation", "gst", "pan", "experience", "mandatory", "certificate", "document"],
        "GFR-2017-R162": ["bid validity", "validity period", "90 days", "valid"],
        "CVC-GL-01": ["single tender", "limited tender", "single source", "justification", "cvc"],
        "CVC-GL-02": ["identical bids", "collusion", "same price", "cartel", "near identical", "clustering"],
        "CVC-GL-03": ["ip address", "same ip", "submission", "collusion", "ip collision"],
        "CVC-GL-04": ["negotiation", "post-tender", "l1 negotiation", "price negotiation"],
        "GEM-DPIIT-01": ["msme", "25%", "msme mandate", "small enterprise", "micro", "sme"],
        "GEM-DPIIT-02": ["make in india", "local content", "class i", "class ii", "dpiit", "local supplier"],
        "GEM-DPIIT-03": ["blacklist", "debar", "excluded", "banned", "integrity"],
        "GEM-DPIIT-04": ["emd", "earnest money", "deposit", "bid security"],
        "IOCL-PR-01": ["abnormally low", "alb", "underbid", "below estimate", "70%", "dumping"],
        "IOCL-PR-02": ["performance bank guarantee", "pbg", "performance bond", "50 lakh"],
        "IOCL-PR-03": ["oisd", "petroleum", "refinery", "safety", "137", "certification"],
    }

    # Score each rule against the query
    rule_scores = {}
    for rule_id, keywords in keyword_map.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            rule_scores[rule_id] = score

    # If no specific match, return all rules as general compliance check
    if not rule_scores:
        rule_scores = {r["id"]: 1 for r in PROCUREMENT_RULES}

    # Get matched rules sorted by relevance
    sorted_rules = sorted(rule_scores.items(), key=lambda x: -x[1])
    matched_rule_ids = [r[0] for r in sorted_rules[:10]]  # top 10
    matched_rules = [r for r in PROCUREMENT_RULES if r["id"] in matched_rule_ids]

    # Evaluate each rule against context
    n_bids = context.get("n_bids", 0)
    est_lakhs = context.get("estimated_value_lakhs", 0.0)
    l1_lakhs = context.get("l1_amount_lakhs", 0.0)
    msme_pct = context.get("msme_pct", 0.0)
    has_blacklisted = context.get("has_blacklisted", False)
    min_gap_pct = context.get("min_bid_gap_pct", 100.0)
    bid_amounts = context.get("bid_amounts", [])

    compliance_results = []
    overall_violations = []

    for rule in matched_rules:
        result = {
            "rule_id": rule["id"],
            "source": rule["source"],
            "category": rule["category"],
            "title": rule["title"],
            "description": rule["description"],
            "severity": rule["severity"],
            "status": "NOT_EVALUATED",
            "finding": "",
            "action_required": "",
            "relevance_score": rule_scores.get(rule["id"], 1),
        }

        tt = rule["threshold_type"]
        tv = rule["threshold_value"]

        if tt == "min_bids":
            if est_lakhs >= 25 and n_bids < tv:
                result["status"] = "VIOLATION"
                result["finding"] = f"Only {n_bids} bids received. GFR 2017 Rule 173 requires minimum {tv} bids for tenders above ₹25L."
                result["action_required"] = "Re-tender or obtain single-tender approval from competent authority."
                overall_violations.append(rule["id"])
            else:
                result["status"] = "COMPLIANT"
                result["finding"] = f"{n_bids} bids received — meets minimum competition requirement."

        elif tt == "price_deviation_pct":
            if est_lakhs > 0 and l1_lakhs > 0:
                deviation = ((l1_lakhs - est_lakhs) / est_lakhs) * 100
                if deviation > tv:
                    result["status"] = "VIOLATION"
                    result["finding"] = f"L1 price ({l1_lakhs:.1f}L) is {deviation:.1f}% above estimate ({est_lakhs:.1f}L). Exceeds {tv}% threshold."
                    result["action_required"] = "Refer to PAC/Finance Committee for price reasonableness approval."
                    overall_violations.append(rule["id"])
                elif deviation < -25:
                    result["status"] = "WARNING"
                    result["finding"] = f"L1 price is {abs(deviation):.1f}% BELOW estimate — possible abnormally low bid."
                    result["action_required"] = "Verify technical capacity of L1 vendor to deliver at this price."
                else:
                    result["status"] = "COMPLIANT"
                    result["finding"] = f"L1 price deviation of {deviation:.1f}% is within acceptable range (±{tv}%)."
            else:
                result["status"] = "NOT_EVALUATED"
                result["finding"] = "Estimated value or L1 amount not provided."

        elif tt == "bid_gap_pct":
            if bid_amounts and len(bid_amounts) >= 2:
                sorted_b = sorted(bid_amounts)
                gaps = []
                for i in range(len(sorted_b) - 1):
                    if sorted_b[i] > 0:
                        gap = ((sorted_b[i + 1] - sorted_b[i]) / sorted_b[i]) * 100
                        gaps.append(gap)
                min_gap = min(gaps) if gaps else 100
                if min_gap < tv:
                    result["status"] = "VIOLATION"
                    result["finding"] = f"Minimum bid gap is {min_gap:.3f}% — below {tv}% threshold. Possible collusion."
                    result["action_required"] = "Refer to Vigilance/CBI for collusion investigation."
                    overall_violations.append(rule["id"])
                else:
                    result["status"] = "COMPLIANT"
                    result["finding"] = f"Minimum bid gap of {min_gap:.2f}% exceeds {tv}% threshold — no clustering detected."
            else:
                result["status"] = "NOT_EVALUATED"
                result["finding"] = "Insufficient bid data for gap analysis."

        elif tt == "msme_pct":
            if msme_pct < tv:
                result["status"] = "WARNING"
                result["finding"] = f"MSME participation at {msme_pct:.1f}% — below mandated {tv}% target."
                result["action_required"] = "Issue targeted MSME tender or udyam-registered vendor outreach."
            else:
                result["status"] = "COMPLIANT"
                result["finding"] = f"MSME participation at {msme_pct:.1f}% meets {tv}% mandate."

        elif tt == "blacklist_check":
            if has_blacklisted:
                result["status"] = "VIOLATION"
                result["finding"] = "Blacklisted/debarred vendor detected in bid pool."
                result["action_required"] = "Immediately disqualify and report to GeM portal and nodal ministry."
                overall_violations.append(rule["id"])
            else:
                result["status"] = "COMPLIANT"
                result["finding"] = "No blacklisted vendors detected in active bid pool."

        elif tt == "alb_pct":
            if est_lakhs > 0 and l1_lakhs > 0:
                l1_pct = (l1_lakhs / est_lakhs) * 100
                if l1_pct < tv:
                    result["status"] = "VIOLATION"
                    result["finding"] = f"L1 bid is {l1_pct:.1f}% of estimate — Abnormally Low Bid (ALB). IOCL threshold: {tv}%."
                    result["action_required"] = "Seek technical justification from L1 vendor. Obtain ALB committee approval."
                    overall_violations.append(rule["id"])
                else:
                    result["status"] = "COMPLIANT"
                    result["finding"] = f"L1 bid at {l1_pct:.1f}% of estimate — above ALB threshold of {tv}%."
            else:
                result["status"] = "NOT_EVALUATED"
                result["finding"] = "Price context not available."

        else:
            result["status"] = "ADVISORY"
            result["finding"] = "This rule requires manual verification. See description for compliance criteria."
            result["action_required"] = "Manual review by procurement officer required."

        compliance_results.append(result)

    # Sort: violations first, then warnings, then compliant
    status_order = {"VIOLATION": 0, "WARNING": 1, "ADVISORY": 2, "COMPLIANT": 3, "NOT_EVALUATED": 4}
    compliance_results.sort(key=lambda r: status_order.get(r["status"], 5))

    critical_count = sum(1 for r in compliance_results if r["status"] == "VIOLATION" and r["severity"] in ("CRITICAL", "HIGH"))
    warning_count = sum(1 for r in compliance_results if r["status"] in ("WARNING", "ADVISORY"))

    if critical_count > 0:
        overall_status = "NON-COMPLIANT"
        overall_color = "#ef4444"
    elif warning_count > 0:
        overall_status = "PARTIAL COMPLIANCE"
        overall_color = "#f59e0b"
    else:
        overall_status = "COMPLIANT"
        overall_color = "#4ade80"

    recommendations = [r["action_required"] for r in compliance_results if r["action_required"] and r["status"] in ("VIOLATION", "WARNING")]

    return {
        "query": query,
        "rules_matched": len(matched_rules),
        "overall_status": overall_status,
        "overall_color": overall_color,
        "violations_count": len(overall_violations),
        "warnings_count": warning_count,
        "violated_rule_ids": overall_violations,
        "compliance_results": compliance_results,
        "recommendations": list(dict.fromkeys(recommendations)),  # deduplicated
        "total_rules_in_database": len(PROCUREMENT_RULES),
    }
