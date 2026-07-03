import os
import requests
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("gem.llm_client")

# Load variables from configuration file with environment fallbacks
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "llm_config.json")

# In-memory config dictionary defaults
config_data = {
    "llm_provider": os.environ.get("LLM_PROVIDER", "ollama").lower(),
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate"),
    "ollama_model": os.environ.get("OLLAMA_MODEL", "llama3"),
    "strict_open_source": os.environ.get("STRICT_OPEN_SOURCE", "true").lower() == "true",
    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
    "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    "strict_accuracy": os.environ.get("STRICT_ACCURACY", "true").lower() == "true",
    "rag_min_relevance": float(os.environ.get("RAG_MIN_RELEVANCE", "40.0")),
    "ollama_model_fast": os.environ.get("OLLAMA_MODEL_FAST", ""),
    "ollama_model_reasoning": os.environ.get("OLLAMA_MODEL_REASONING", ""),
    "rag_semantic_weight": float(os.environ.get("RAG_SEMANTIC_WEIGHT", "0.7")),
}

def load_config():
    global config_data
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                config_data.update(data)
        except Exception as e:
            logger.error(f"[llm_client] Failed to load config: {e}")

def save_config(new_config: dict):
    global config_data
    config_data.update(new_config)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"[llm_client] Failed to save config: {e}")
        return False

# Initialize config
load_config()

# Deprecated: kept for compatibility
ACTIVE_PROVIDER = "ollama"

def set_provider(provider: str) -> bool:
    load_config()
    p_lower = provider.lower().strip()
    strict = config_data.get("strict_open_source", True)
    if strict and p_lower in ["gemini", "openai"]:
        logger.warning(f"[llm_client] Rejected setting provider to '{p_lower}' because STRICT_OPEN_SOURCE is enabled.")
        return False
    if p_lower in ["gemini", "openai", "ollama"]:
        config_data["llm_provider"] = p_lower
        save_config(config_data)
        logger.info(f"[llm_client] Active provider set to: {p_lower}")
        return True
    return False

def get_provider_status() -> Dict[str, Any]:
    load_config()
    strict = config_data.get("strict_open_source", True)
    active = "ollama" if strict else config_data.get("llm_provider", "ollama")
    return {
        "configured_provider": config_data.get("llm_provider", "ollama"),
        "active_provider": active,
        "gemini_configured": False if strict else bool(config_data.get("gemini_api_key", "")),
        "openai_configured": False if strict else bool(config_data.get("openai_api_key", "")),
        "ollama_url": config_data.get("ollama_url", ""),
        "ollama_model": config_data.get("ollama_model", ""),
        "strict_open_source": strict,
        "gemini_model": config_data.get("gemini_model", "gemini-1.5-flash"),
        "openai_model": config_data.get("openai_model", "gpt-4o-mini"),
        "strict_accuracy": config_data.get("strict_accuracy", True),
        "rag_min_relevance": config_data.get("rag_min_relevance", 40.0),
        "ollama_model_fast": config_data.get("ollama_model_fast", ""),
        "ollama_model_reasoning": config_data.get("ollama_model_reasoning", ""),
        "rag_semantic_weight": config_data.get("rag_semantic_weight", 0.7)
    }

STRICT_ACCURACY_PROMPT = (
    "STRICT GROUNDING & ZERO HALLUCINATION DIRECTIVE:\n"
    "1. Do NOT assume, speculate, or extrapolate. Answer ONLY using direct factual evidence from the provided context.\n"
    "2. If the context does not contain the answer, say: 'I cannot find the answer in the provided documents.'\n"
    "3. Ensure every factual claim, number, or specification has a direct citation to the source document."
)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "llm_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

_redis_client = None
_redis_available = False
_redis_checked = False

def _get_redis_client():
    global _redis_client, _redis_available, _redis_checked
    if _redis_checked:
        return _redis_client if _redis_available else None
    
    _redis_checked = True
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info(f"[llm_client] Connected to Redis for LLM caching: {redis_url}")
        return _redis_client
    except Exception as e:
        _redis_available = False
        _redis_client = None
        logger.debug(f"[llm_client] Redis caching unavailable (falling back to file cache): {e}")
        return None

def _get_cache_key(prompt: str, system_instruction: Optional[str], temperature: float) -> str:
    import hashlib
    hash_input = f"{prompt}|||{system_instruction or ''}|||{temperature}"
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

def _read_cache(key: str) -> Optional[str]:
    # Try Redis first
    r = _get_redis_client()
    if r:
        try:
            val = r.get(f"llm_cache:{key}")
            if val:
                return val.decode("utf-8")
        except Exception:
            pass

    cache_path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(cache_path):
        try:
            import time
            # Enforce 24-hour TTL on file cache entries
            mtime = os.path.getmtime(cache_path)
            if time.time() - mtime > 86400:
                os.remove(cache_path)
                return None
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("response")
        except Exception:
            pass
    return None

def _write_cache(key: str, response: str, prompt: str):
    # Try Redis first
    r = _get_redis_client()
    if r:
        try:
            r.setex(f"llm_cache:{key}", 86400, response)
        except Exception:
            pass

    cache_path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "response": response,
                "prompt_preview": prompt[:300]
            }, f, indent=4)
    except Exception:
        pass


def generate_text(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.0, is_verification_query: bool = False, response_format: Optional[str] = None, task_tier: str = "default", force_refresh: bool = False) -> str:
    # Check cache first (incorporate response_format in hash)
    import hashlib
    hash_input = f"{prompt}|||{system_instruction or ''}|||{temperature}|||{response_format or ''}"
    cache_key = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    if not force_refresh:
        cached_val = _read_cache(cache_key)
        if cached_val is not None:
            logger.info(f"[llm_client] Returning cached response for prompt (len={len(prompt)})")
            return cached_val

    load_config()
    provider = config_data.get("llm_provider", "ollama").lower().strip()
    strict = config_data.get("strict_open_source", True)
    if strict and provider in ["gemini", "openai"]:
        logger.warning(f"[llm_client] Overriding provider '{provider}' to 'ollama' because STRICT_OPEN_SOURCE is enabled.")
        provider = "ollama"

    response = ""
    if provider == "gemini":
        response = _call_gemini(prompt, system_instruction, temperature, response_format)
    elif provider == "openai":
        response = _call_openai(prompt, system_instruction, temperature, response_format)
    else:  # ollama
        model = None
        if task_tier == "reasoning" and config_data.get("ollama_model_reasoning"):
            model = config_data.get("ollama_model_reasoning")
        elif task_tier == "fast" and config_data.get("ollama_model_fast"):
            model = config_data.get("ollama_model_fast")
        if not model:
            model = config_data.get("ollama_model", "llama3")
        response = _call_ollama(prompt, system_instruction, temperature, response_format, model=model)

    _write_cache(cache_key, response, prompt)
    return response


def generate_with_vision(prompt: str, img_b64: str, mime_type: str = "image/jpeg", system_instruction: Optional[str] = None, temperature: float = 0.0) -> str:
    """
    Generate text response from a multimodal Vision LLM (Gemini or OpenAI).
    Only executed if strict_open_source is False.
    """
    load_config()
    provider = config_data.get("llm_provider", "ollama").lower().strip()
    strict = config_data.get("strict_open_source", True)
    if strict:
        logger.warning("[llm_client] generate_with_vision blocked: STRICT_OPEN_SOURCE compliance is active.")
        return ""

    if provider == "gemini":
        key = config_data.get("gemini_api_key", "")
        if not key:
            logger.warning("[llm_client] Gemini API key not configured for Vision OCR.")
            return ""
        model = config_data.get("gemini_model", "gemini-1.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": img_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": temperature
            }
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        try:
            resp = requests.post(url, json=payload, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            else:
                logger.error(f"[llm_client] Gemini Vision API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[llm_client] Gemini Vision call failed: {e}")

    elif provider == "openai":
        key = config_data.get("openai_api_key", "")
        if not key:
            logger.warning("[llm_client] OpenAI API key not configured for Vision OCR.")
            return ""
        model = config_data.get("openai_model", "gpt-4o-mini")
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{img_b64}"
                        }
                    }
                ]
            }],
            "temperature": temperature
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=45)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                logger.error(f"[llm_client] OpenAI Vision API error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"[llm_client] OpenAI Vision call failed: {e}")

    return ""


def heal_json_response(data: dict, expected_keys: list) -> dict:
    """Ensure all expected keys are present in the dictionary. If not, initialize with default values."""
    if not isinstance(data, dict):
        return {}
    
    # Simple type heuristics based on common procurement keys
    defaults = {
        "rules": [],
        "verdicts": [],
        "failed_mandatory": [],
        "risk_factors": [],
        "certifications": [],
        "required_certifications": [],
        "required_documents": [],
        "keywords": [],
        "overall_pass": True,
        "score_pct": 0.0,
        "total_score": 0.0,
        "max_possible_score": 0.0,
        "score": 0.0,
        "max_score": 0.0,
        "confidence": 80,
        "needs_human_review": False,
        "company_name": None,
        "gem_reg_no": None,
        "gstin": None,
        "pan_number": None,
        "msme_registered": False,
        "make_in_india": False,
        "annual_turnover_cr": None,
        "net_worth_cr": None,
        "years_in_business": None,
        "summary": "Evaluation complete.",
        "rationale": "Evaluation complete.",
        "evidence_quote": "No direct evidence found."
    }

    for key in expected_keys:
        if key not in data:
            data[key] = defaults.get(key, None)
    return data

def repair_json_string(s: str) -> str:
    """
    Attempt to programmatically repair common JSON syntax errors produced by local open-source LLMs.
    """
    s = s.strip()
    
    # 1. Extract block starting from first { or first [
    first_brace = s.find('{')
    first_bracket = s.find('[')
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        last_brace = s.rfind('}')
        if last_brace != -1 and last_brace > first_brace:
            s = s[first_brace:last_brace+1]
        else:
            s = s[first_brace:]
    elif first_bracket != -1:
        last_bracket = s.rfind(']')
        if last_bracket != -1 and last_bracket > first_bracket:
            s = s[first_bracket:last_bracket+1]
        else:
            s = s[first_bracket:]
            
    s = s.strip()
    
    # 2. Handle Python-style booleans/None if they slipped in
    import re
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)
    
    # 3. Clean up unclosed double quotes (if odd count, append quote)
    if s.count('"') % 2 != 0:
        s += '"'
        
    # 4. Fix trailing commas/colons before closing braces/brackets
    s = s.strip()
    if s.endswith(','):
        s = s[:-1].strip()
    elif s.endswith(':'):
        s = s[:-1].strip()
        if s.endswith(','):
            s = s[:-1].strip()
            
    # Also clean commas inside JSON structures before closing braces/brackets
    s = re.sub(r',\s*([}\])])', r'\1', s)
    
    # 5. Balance unclosed braces/brackets due to token cutoff
    open_braces = s.count('{')
    close_braces = s.count('}')
    open_brackets = s.count('[')
    close_brackets = s.count(']')
    
    if open_braces > close_braces:
        s += '}' * (open_braces - close_braces)
    if open_brackets > close_brackets:
        s += ']' * (open_brackets - close_brackets)
        
    return s

def generate_json(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.0, expected_keys: Optional[list] = None, task_tier: str = "default") -> dict:
    """
    Generates JSON content by instructing the model to reply in JSON format and parsing it.
    Optional expected_keys runs a healing pass on the parsed output.
    """
    load_config()
    if config_data.get("strict_accuracy", True):
        temperature = 0.0
        strict_json_directive = (
            "STRICT GROUNDING & ZERO HALLUCINATION DIRECTIVE:\n"
            "Every field in the returned JSON object must be based strictly on facts present in the context. "
            "Do not invent any data or fields not supported by the context."
        )
        if system_instruction:
            system_instruction = f"{system_instruction}\n\n{strict_json_directive}"
        else:
            system_instruction = strict_json_directive

    json_prompt = (
        f"{prompt}\n\n"
        "CRITICAL: Return ONLY a valid JSON object. "
        "Do NOT wrap in markdown code blocks like ```json ... ```. "
        "Do NOT write any introduction or explanation. "
        "Your entire response must be valid JSON, starting with '{' and ending with '}'."
    )
    res_text = generate_text(json_prompt, system_instruction, temperature, is_verification_query=True, response_format="json", task_tier=task_tier)
    
    # Clean output in case LLM wraps in code fences despite instructions
    res_text_clean = res_text.strip()
    if res_text_clean.startswith("```json"):
        res_text_clean = res_text_clean[7:]
    elif res_text_clean.startswith("```"):
        res_text_clean = res_text_clean[3:]
    if res_text_clean.endswith("```"):
        res_text_clean = res_text_clean[:-3]
    res_text_clean = res_text_clean.strip()
    
    try:
        parsed = json.loads(res_text_clean)
        if expected_keys:
            parsed = heal_json_response(parsed, expected_keys)
        return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"[llm_client] Initial JSON parse failed. Attempting repair. Error: {e}")
        repaired_text = res_text_clean
        try:
            repaired_text = repair_json_string(res_text_clean)
            parsed = json.loads(repaired_text)
            if expected_keys:
                parsed = heal_json_response(parsed, expected_keys)
            logger.info("[llm_client] JSON repaired and parsed successfully.")
            return parsed
        except Exception as e_repair:
            logger.error(f"[llm_client] Repair failed. Repaired text: {repaired_text}. Error: {e_repair}")
            # Secondary fallback regex/bracket extraction
            start_idx = res_text.find("{")
            end_idx = res_text.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                try:
                    parsed = json.loads(res_text[start_idx:end_idx+1])
                    if expected_keys:
                        parsed = heal_json_response(parsed, expected_keys)
                    return parsed
                except Exception:
                    pass
            
            # Fallback healing to avoid endpoint crashes
            if expected_keys:
                logger.warning("[llm_client] JSON parsing failed completely. Returning healed default dictionary.")
                return heal_json_response({}, expected_keys)
            raise e


def extract_structured(text: str, schema_desc: str, retries: int = 2) -> dict:
    """
    Extract structured fields from document text using the LLM.
    Retries on JSON parse failure with a stricter re-prompt.

    Args:
        text: Raw document text (OCR output, etc.)
        schema_desc: Natural language description of the fields to extract
        retries: Number of retry attempts on parse failure

    Returns:
        dict of extracted fields, or empty dict on total failure
    """
    system = (
        "You are a precise document data extraction engine for a Government procurement system. "
        "Extract ONLY the fields explicitly mentioned in the schema. "
        "If a field is not found in the document, use null. "
        "Never invent or estimate values."
    )
    prompt = (
        f"Extract the following fields from the document text below.\n\n"
        f"SCHEMA (fields to extract):\n{schema_desc}\n\n"
        f"DOCUMENT TEXT:\n{text[:60000]}\n\n"
        f"Return a JSON object with exactly the fields described. "
        f"Use null for any field not found in the document."
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            return generate_json(prompt, system_instruction=system, temperature=0.0)
        except Exception as e:
            last_error = e
            if attempt < retries:
                # Re-prompt with even stricter instruction
                prompt = (
                    f"Previous attempt failed to produce valid JSON. Try again.\n\n"
                    f"Extract ONLY these fields: {schema_desc}\n\n"
                    f"TEXT: {text[:60000]}\n\n"
                    f"Respond with ONLY a JSON object. No explanation. No markdown."
                )
    logger.warning(f"[llm_client] extract_structured failed after {retries+1} attempts: {last_error}")
    return {}


def verify_citations(answer: str, citations: Any, context_text: str) -> dict:
    """
    Verbatim Citation Guard (VCG) to programmatically validate LLM citations.
    Checks:
      1. Verbatim Grounding: Quotes must exist verbatim (or normalized/near-verbatim) in context_text.
      2. Policy Validity: Standard GFR/CVC/GeM references must contain recognized keywords and rule numbers.
    """
    if not citations:
        return {
            "is_verified": True,
            "verified_citations": [],
            "hallucinated_citations": [],
            "status": "NO_CITATIONS"
        }

    import re

    # Standard recognized policies/guidelines
    KNOWN_POLICIES = [
        "gfr", "general financial rules", "cvc", "central vigilance commission", 
        "gem", "government e-marketplace", "msme", "micro small", "udyam", 
        "dpiit", "make in india", "mii", "indian contract act", "oisd"
    ]

    def normalize(text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    context_normalized = normalize(context_text)

    # Normalize citations input to a list of dicts
    citation_list = []
    if isinstance(citations, list):
        for c in citations:
            if isinstance(c, dict):
                citation_list.append(c)
            elif isinstance(c, str):
                citation_list.append({"quote": c, "source_document": "Unknown"})
    elif isinstance(citations, dict):
        citation_list.append(citations)
    elif isinstance(citations, str):
        if "\n" in citations:
            for line in citations.split("\n"):
                if line.strip():
                    citation_list.append({"quote": line.strip(), "source_document": "Unknown"})
        elif ";" in citations:
            for item in citations.split(";"):
                if item.strip():
                    citation_list.append({"quote": item.strip(), "source_document": "Unknown"})
        else:
            citation_list.append({"quote": citations.strip(), "source_document": "Unknown"})

    verified_list = []
    hallucinated_list = []
    is_verified = True

    for cit in citation_list:
        quote = cit.get("quote", "") or cit.get("evidence", "") or cit.get("text", "") or cit.get("citations", "")
        if not quote and len(cit) == 1:
            quote = list(cit.values())[0]

        quote_str = str(quote).strip()
        source = cit.get("source_document", "") or cit.get("source", "Unknown")

        if not quote_str or quote_str.lower() in [
            "no evidence found", "no direct evidence found", "no evidence", 
            "none", "null", "no citation", "unspecified", "not specified"
        ]:
            verified_list.append({
                "quote": quote_str,
                "source": source,
                "verified": True,
                "reason": "Empty or negative citation placeholder"
            })
            continue

        norm_quote = normalize(quote_str)
        
        # 1. Verbatim check in source context
        if norm_quote and norm_quote in context_normalized:
            verified_list.append({
                "quote": quote_str,
                "source": source,
                "verified": True,
                "match_type": "verbatim_grounded"
            })
            continue

        # 2. Check if it's a valid standard policy reference
        is_policy_ref = False
        quote_lower = quote_str.lower()
        for policy in KNOWN_POLICIES:
            if policy in quote_lower:
                if any(kw in quote_lower for kw in ["rule", "circular", "order", "act", "section", "sec", "clause", "2017", "2023", "2024", "2012"]):
                    is_policy_ref = True
                    break

        if is_policy_ref:
            verified_list.append({
                "quote": quote_str,
                "source": source,
                "verified": True,
                "match_type": "policy_referenced"
            })
        else:
            is_verified = False
            hallucinated_list.append({
                "quote": quote_str,
                "source": source,
                "verified": False,
                "reason": "Quote not found verbatim in context and does not reference recognized procurement policies"
            })
            verified_list.append({
                "quote": quote_str,
                "source": source,
                "verified": False,
                "reason": "Quote not found verbatim in context and does not reference recognized procurement policies"
            })

    return {
        "is_verified": is_verified,
        "verified_citations": verified_list,
        "hallucinated_citations": hallucinated_list,
        "status": "VERIFIED" if is_verified else "HALLUCINATION_DETECTED"
    }


def score_with_evidence(
    criteria_name: str,
    max_score: float,
    context_chunks: list,
    vendor_name: str = "",
    temperature: float = 0.0
) -> dict:
    """
    Score a procurement criterion using RAG context chunks.
    Returns score + mandatory evidence quote + confidence level.
    Makes AI scoring fully auditable.

    Returns:
        {
            "score": float,
            "rationale": str,
            "evidence_quote": str,   # Direct quote from document
            "confidence": int,       # 0-100
            "needs_human_review": bool
        }
    """
    context_text = "\n\n---\n\n".join(
        f"[Doc {i+1}]: {chunk}" for i, chunk in enumerate(context_chunks[:5])
    ) if context_chunks else "No supporting documents available."

    raw_context = "\n".join(context_chunks) if context_chunks else ""

    vendor_clause = f" for vendor '{vendor_name}'" if vendor_name else ""

    prompt = (
        f"You are a procurement evaluation officer. Score the following criterion{vendor_clause}.\n\n"
        f"CRITERION: {criteria_name}\n"
        f"MAX SCORE: {max_score}\n\n"
        f"SUPPORTING DOCUMENTS:\n{context_text}\n\n"
        f"Instructions:\n"
        f"1. Find the most relevant sentence(s) in the documents as evidence.\n"
        f"2. Assign a score from 0 to {max_score} based ONLY on the evidence.\n"
        f"3. If no evidence exists, score 0.\n"
        f"4. Estimate your confidence (0-100) that the evidence directly supports the score.\n\n"
        f"Return a JSON object with these exact fields:\n"
        f"- score: (number, 0 to {max_score})\n"
        f"- rationale: (one sentence explaining the score)\n"
        f"- evidence_quote: (exact quote from the document, or 'No evidence found')\n"
        f"- confidence: (integer 0-100)\n"
        f"- needs_human_review: (true if confidence < 60 or evidence is ambiguous)"
    )
    system = (
        "You are a strict procurement evaluator. "
        "You MUST cite evidence. Never invent scores without document support. "
        "If no evidence exists, score must be 0."
    )
    try:
        result = generate_json(prompt, system_instruction=system, temperature=temperature)
        quote = result.get("evidence_quote", "No evidence found.")
        
        # Verify citation
        cit_check = verify_citations(
            answer=result.get("rationale", ""),
            citations=quote,
            context_text=raw_context
        )
        
        # Self-correction loop: retry once if hallucinated
        if not cit_check.get("is_verified", False) and raw_context:
            logger.warning(f"[llm_client] VCG detected hallucinated quote: '{quote}'. Retrying with strict instruction...")
            retry_prompt = (
                f"{prompt}\n\n"
                f"CRITICAL: Your previous evidence_quote '{quote}' was rejected because it does not exist verbatim in the text.\n"
                f"You MUST select an EXACT verbatim quote from the text. Check spelling, capitalization, and spaces carefully.\n"
                f"If no exact quote exists, return 'No evidence found' and score 0."
            )
            try:
                result = generate_json(retry_prompt, system_instruction=system, temperature=0.0)
                quote = result.get("evidence_quote", "No evidence found.")
                cit_check = verify_citations(
                    answer=result.get("rationale", ""),
                    citations=quote,
                    context_text=raw_context
                )
            except Exception as e_retry:
                logger.warning(f"[llm_client] VCG retry failed: {e_retry}")

        # Validate and clamp
        score = float(result.get("score", 0))
        score = max(0.0, min(float(max_score), score))
        confidence = int(result.get("confidence", 50))
        
        # If still not verified, reduce confidence and flag review
        final_verified = cit_check.get("is_verified", False)
        if not final_verified and quote.lower() not in ["no evidence found", "no direct evidence found", "no evidence", "none", "null"]:
            confidence = min(confidence, 40)

        return {
            "score": round(score, 2),
            "rationale": str(result.get("rationale", "No rationale provided.")),
            "evidence_quote": str(quote),
            "confidence": confidence,
            "needs_human_review": confidence < 60 or result.get("needs_human_review", False) or not final_verified,
            "citation_verified": final_verified,
            "citation_details": cit_check
        }
    except Exception as e:
        logger.warning(f"[llm_client] score_with_evidence failed: {e}")
        return {
            "score": 0.0,
            "rationale": f"AI scoring failed: {e}",
            "evidence_quote": "No evidence found.",
            "confidence": 0,
            "needs_human_review": True,
            "citation_verified": False
        }


def chain_of_thought(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.1) -> str:
    """
    Wraps a prompt in step-by-step chain-of-thought reasoning.
    Forces the model to reason before concluding — reduces hallucination
    significantly for complex procurement analysis tasks.
    """
    cot_system = (
        (system_instruction + "\n\n") if system_instruction else ""
    ) + (
        "Think step by step. "
        "First list your reasoning steps numbered 1, 2, 3... "
        "Then state your final conclusion after 'CONCLUSION:'. "
        "Base every step only on the evidence provided."
    )
    cot_prompt = (
        f"{prompt}\n\n"
        "Work through this step by step, then give your final answer after 'CONCLUSION:'."
    )
    raw = generate_text(cot_prompt, system_instruction=cot_system, temperature=temperature, is_verification_query=True)
    # Extract conclusion if present
    if "CONCLUSION:" in raw:
        return raw.split("CONCLUSION:")[-1].strip()
    return raw.strip()



def test_connection(provider: str) -> Dict[str, Any]:
    """
    Test connectivity to a specific provider.
    """
    p_lower = provider.lower().strip()
    load_config()
    strict = config_data.get("strict_open_source", True)
    if strict and p_lower in ["gemini", "openai"]:
        return {"status": "error", "message": f"{provider.capitalize()} is disabled due to STRICT_OPEN_SOURCE compliance mode."}

    test_prompt = "Respond with 'OK' and nothing else."
    try:
        if p_lower == "gemini":
            if not config_data.get("gemini_api_key", ""):
                return {"status": "error", "message": "Gemini API key is not configured."}
            res = _call_gemini(test_prompt, temperature=0.1)
            return {"status": "success", "response": res}
        elif p_lower == "openai":
            if not config_data.get("openai_api_key", ""):
                return {"status": "error", "message": "OpenAI API key is not configured."}
            res = _call_openai(test_prompt, temperature=0.1)
            return {"status": "success", "response": res}
        elif p_lower == "ollama":
            res = _call_ollama(test_prompt, temperature=0.1)
            return {"status": "success", "response": res}
        else:
            return {"status": "error", "message": f"Unknown provider: {provider}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _call_gemini(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.2, response_format: Optional[str] = None) -> str:
    key = config_data.get("gemini_api_key", "")
    model = config_data.get("gemini_model", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": temperature
        }
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
    if response_format == "json":
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f"Gemini API returned status code {resp.status_code}: {resp.text}")
        
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected response structure from Gemini API: {data}. Error: {e}")

def _call_openai(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.2, response_format: Optional[str] = None) -> str:
    key = config_data.get("openai_api_key", "")
    model = config_data.get("openai_model", "gpt-4o-mini")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature
    }
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f"OpenAI API returned status code {resp.status_code}: {resp.text}")
        
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise ValueError(f"Unexpected response structure from OpenAI API: {data}. Error: {e}")

def _call_ollama(prompt: str, system_instruction: Optional[str] = None, temperature: float = 0.2, response_format: Optional[str] = None, model: Optional[str] = None) -> str:
    """
    Call Ollama using the /api/chat endpoint with proper messages[] format.
    This is significantly more accurate than the legacy /api/generate approach
    because instruction-tuned models are trained on the chat message format.
    """
    if not model:
        model = config_data.get("ollama_model", "mistral:7b-instruct")

    # Build base URL — swap /api/generate -> /api/chat automatically
    base_url = config_data.get("ollama_url", "http://localhost:11434/api/generate")
    chat_url = base_url.replace("/api/generate", "/api/chat")

    # Construct proper messages array
    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,          # Larger context window for long tender docs
            "repeat_penalty": 1.1,    # Reduce repetitive hallucinations
            "top_p": 0.9,             # Nucleus sampling for coherent output
            "top_k": 40,              # Limits vocabulary for precision
            "num_predict": 1024,      # Max tokens in response
        }
    }
    if response_format == "json":
        payload["format"] = "json"

    try:
        resp = requests.post(chat_url, json=payload, timeout=120)
        if resp.status_code != 200:
            raise ValueError(f"Ollama chat API returned status {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        # /api/chat returns: {"message": {"role": "assistant", "content": "..."}}
        content = data.get("message", {}).get("content", "")
        if content:
            return content.strip()
        # Fallback: some versions return "response" key
        return data.get("response", "").strip()

    except requests.exceptions.Timeout:
        raise ConnectionError(f"Ollama timed out after 120s. Model '{model}' may be too slow — try a smaller model.")
    except requests.exceptions.ConnectionError:
        raise ConnectionError("Ollama is not running. Start it with: ollama serve")
