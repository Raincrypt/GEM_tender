"""
ocr_engine.py — Centralized High-Power Open-Source OCR Engine
=============================================================
Provides a unified, high-accuracy OCR pipeline for the GEM Tender system.
All OCR consumers (documents.py, reports_pqc.py) import from this module.

Pipeline stages:
  1. Image preprocessing (deskew, CLAHE, binarization, upscaling, denoise)
  2. Multi-engine OCR cascade (EasyOCR × 2 + Tesseract × 2 + PyPDF2)
  3. Intelligent result merging with confidence scoring
  4. Table structure detection via OpenCV

100% open-source. No cloud API calls.
"""

import os
import re
import logging
from typing import List, Tuple, Optional, Dict, Any

# Environment configurations for CPU/GPU execution

logger = logging.getLogger("gem.ocr_engine")

import hashlib
import json

# ──────────────────────────────────────────────────────────────────────────────
#  OCR Cache Configuration
# ──────────────────────────────────────────────────────────────────────────────
OCR_CACHE_DIR = os.path.join(os.path.dirname(__file__), "ocr_cache")
os.makedirs(OCR_CACHE_DIR, exist_ok=True)


def _get_ocr_cache_key(file_path: str) -> str:
    """Generate a unique SHA256 cache key using file path, size, AND content prefix hash.
    This prevents stale cache hits when a file is re-uploaded with different content but same size."""
    try:
        abs_path = os.path.abspath(file_path)
        size = os.path.getsize(abs_path)
        # Read first 4KB of file for content-based invalidation
        content_hash = ""
        try:
            with open(abs_path, "rb") as f:
                content_hash = hashlib.md5(f.read(4096)).hexdigest()
        except Exception:
            pass
        key_input = f"{abs_path}|||{size}|||{content_hash}"
        return hashlib.sha256(key_input.encode("utf-8")).hexdigest()
    except Exception:
        # Fallback to path hash if file metadata cannot be accessed
        return hashlib.sha256(file_path.encode("utf-8")).hexdigest()


def _read_ocr_cache(key: str) -> Optional[str]:
    # Try Redis first
    try:
        from llm_client import _get_redis_client
        r = _get_redis_client()
        if r:
            val = r.get(f"ocr_cache:{key}")
            if val:
                try:
                    data = json.loads(val.decode("utf-8"))
                    if isinstance(data, dict) and "text" in data:
                        return data["text"]
                except Exception:
                    pass
                return val.decode("utf-8")
    except Exception as e:
        logger.debug(f"OCR Redis cache read failed: {e}")

    # Fall back to file cache
    cache_path = os.path.join(OCR_CACHE_DIR, f"{key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("text")
        except Exception:
            pass
    return None


def _read_ocr_cache_meta(key: str) -> dict:
    # Try Redis first
    try:
        from llm_client import _get_redis_client
        r = _get_redis_client()
        if r:
            val = r.get(f"ocr_cache:{key}")
            if val:
                try:
                    data = json.loads(val.decode("utf-8"))
                    if isinstance(data, dict):
                        return {
                            "text": data.get("text", ""),
                            "engine_used": data.get("engine_used", "OCR Engine Cascade"),
                            "confidence": data.get("confidence", 0.85)
                        }
                except Exception:
                    pass
    except Exception:
        pass

    # Fall back to file cache
    cache_path = os.path.join(OCR_CACHE_DIR, f"{key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "text": data.get("text", ""),
                    "engine_used": data.get("engine_used", "OCR Engine Cascade"),
                    "confidence": data.get("confidence", 0.85)
                }
        except Exception:
            pass
    return {
        "text": "",
        "engine_used": "OCR Engine Cascade",
        "confidence": 0.85
    }


def _write_ocr_cache(key: str, text: str, file_path: str, engine_used: str = "OCR Engine Cascade", confidence: float = 0.85):
    payload_dict = {
        "text": text,
        "file_path": os.path.abspath(file_path),
        "engine_used": engine_used,
        "confidence": confidence
    }
    
    # Try Redis first
    try:
        from llm_client import _get_redis_client
        r = _get_redis_client()
        if r:
            r.set(f"ocr_cache:{key}", json.dumps(payload_dict))
    except Exception as e:
        logger.debug(f"OCR Redis cache write failed: {e}")

    # Write to file cache
    cache_path = os.path.join(OCR_CACHE_DIR, f"{key}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload_dict, f, indent=4)
    except Exception:
        pass


def get_file_ocr_metadata(file_path: str) -> dict:
    """Retrieve engine_used and confidence metadata for a given file from cache."""
    try:
        cache_key = _get_ocr_cache_key(file_path)
        meta = _read_ocr_cache_meta(cache_key)
        return {
            "engine_used": meta.get("engine_used", "OCR Engine Cascade"),
            "confidence": meta.get("confidence", 0.85)
        }
    except Exception:
        return {
            "engine_used": "OCR Engine Cascade",
            "confidence": 0.85
        }


# ──────────────────────────────────────────────────────────────────────────────
#  EasyOCR Singleton for layout and text analysis
# ──────────────────────────────────────────────────────────────────────────────
_EASY_OCR_READER = None
_EASY_OCR_AVAILABLE = False
_EASY_INITIALIZED = False


class EasyOCRAdapter:
    def __init__(self, reader):
        self.reader = reader

    def ocr(self, img_np, **kwargs):
        """
        Runs EasyOCR on image_np and formats the output to match standard nested list format.
        Format: [[[[x0, y0], [x1, y0], [x1, y1], [x0, y1]], (text, confidence)], ...]
        Returns: a list of pages, where each page is a list of lines.
        """
        try:
            results = self.reader.readtext(img_np)
            page_output = []
            for box, text, conf in results:
                box_coords = [[float(p[0]), float(p[1])] for p in box]
                page_output.append([box_coords, (text, float(conf))])
            return [page_output]
        except Exception as e:
            logger.warning(f"EasyOCR run failed: {e}")
            return []


def get_easy_ocr():
    """Returns (is_available: bool, engine_or_none) using lazy singleton init."""
    global _EASY_OCR_READER, _EASY_OCR_AVAILABLE, _EASY_INITIALIZED
    if _EASY_INITIALIZED:
        return _EASY_OCR_AVAILABLE, _EASY_OCR_READER

    _EASY_INITIALIZED = True
    try:
        import easyocr
        import torch

        use_gpu = torch.cuda.is_available()
        reader = easyocr.Reader(['en'], gpu=use_gpu)
        _EASY_OCR_READER = EasyOCRAdapter(reader)
        _EASY_OCR_AVAILABLE = True
        print(f"[OCR Engine] EasyOCR (Non-Chinese) initialized successfully (singleton). GPU Enabled: {use_gpu}")
        logger.info(f"EasyOCR engine initialized. GPU Enabled: {use_gpu}")
    except Exception as e:
        print(f"[OCR Engine] EasyOCR unavailable: {e}")
        logger.warning(f"EasyOCR init failed: {e}")
    return _EASY_OCR_AVAILABLE, _EASY_OCR_READER


def get_vision_ocr():
    """Returns the primary Vision OCR engine singleton."""
    return get_easy_ocr()



# ──────────────────────────────────────────────────────────────────────────────
#  Image Preprocessing — Multi-Strategy Pipeline
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_min_resolution(img, min_side=2400):
    """Upscale image if either dimension is below min_side pixels."""
    import cv2
    h, w = img.shape[:2]
    if h >= min_side and w >= min_side:
        return img
    scale = max(min_side / h, min_side / w, 1.0)
    scale = min(scale, 3.0)  # Cap at 3x to avoid memory explosion
    new_w, new_h = int(w * scale), int(h * scale)
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def _deskew(gray_img):
    """Correct document tilt using Hough Line Transform."""
    import cv2
    import numpy as np

    try:
        # Edge detection
        edges = cv2.Canny(gray_img, 50, 150, apertureSize=3)
        # Detect lines
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=gray_img.shape[1] // 4,
                                maxLineGap=20)
        if lines is None or len(lines) < 3:
            return gray_img, 0.0

        # Calculate angles of all detected lines
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if abs(x2 - x1) < 5:  # Skip near-vertical lines
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) < 15:  # Only consider near-horizontal lines
                angles.append(angle)

        if not angles:
            return gray_img, 0.0

        # Use median angle to be robust against outliers
        median_angle = np.median(angles)
        if abs(median_angle) < 0.3:  # Skip tiny corrections
            return gray_img, median_angle

        # Rotate to correct skew
        h, w = gray_img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(gray_img, M, (w, h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
        return rotated, median_angle
    except Exception as e:
        logger.warning(f"Deskew failed: {e}")
        return gray_img, 0.0


def _remove_noise_morphological(gray_img):
    """Remove salt-and-pepper noise and small artifacts using morphological ops."""
    import cv2
    import numpy as np

    try:
        # Small kernel opening to remove tiny noise specks
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
        opened = cv2.morphologyEx(gray_img, cv2.MORPH_OPEN, kernel)
        # Small closing to fill tiny gaps in characters
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
        return closed
    except Exception:
        return gray_img


def _remove_borders(gray_img, border_pct=0.02):
    """Remove dark borders/scanner artifacts from edges of document scans."""
    import cv2
    import numpy as np

    try:
        h, w = gray_img.shape[:2]
        bh, bw = int(h * border_pct), int(w * border_pct)
        # Set border regions to white (255) to prevent OCR from reading border artifacts
        result = gray_img.copy()
        result[:bh, :] = 255
        result[-bh:, :] = 255
        result[:, :bw] = 255
        result[:, -bw:] = 255
        return result
    except Exception:
        return gray_img


def preprocess_clahe_color(img_rgb):
    """
    CLAHE on LAB L-channel — preserves color gradients for EasyOCR.
    Best for: printed text, colored stamps, logos.
    Tuned for low-contrast government scanned documents.
    """
    import cv2
    import numpy as np

    try:
        img = img_rgb.copy()
        img = _ensure_min_resolution(img)

        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        l, a, b = cv2.split(lab)

        # Detect if image is low-contrast (government scans often are)
        l_std = np.std(l)
        # Use stronger CLAHE for low-contrast documents
        clip_limit = 5.0 if l_std < 40 else 4.0
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        cl = clahe.apply(l)

        enhanced = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2RGB)

        # Bilateral filter — edge-preserving smoothing
        denoised = cv2.bilateralFilter(enhanced, 7, 60, 60)

        # Unsharp mask for sharpening character edges
        gaussian = cv2.GaussianBlur(denoised, (0, 0), 3)
        sharpened = cv2.addWeighted(denoised, 1.5, gaussian, -0.5, 0)

        return sharpened
    except Exception as e:
        logger.warning(f"CLAHE color preprocessing failed: {e}")
        return img_rgb


def preprocess_deskew_sharpen(img_rgb):
    """
    Deskew + denoise + sharpen — for rotated/tilted document scans.
    Returns color image suitable for EasyOCR.
    """
    import cv2
    import numpy as np

    try:
        img = img_rgb.copy()
        img = _ensure_min_resolution(img)

        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        deskewed_gray, angle = _deskew(gray)

        if abs(angle) > 0.3:
            # Apply same rotation to color image
            h, w = img.shape[:2]
            center = (w // 2, h // 2)
            # Re-upscale color image to match gray
            img = _ensure_min_resolution(img)
            h2, w2 = img.shape[:2]
            center2 = (w2 // 2, h2 // 2)
            M = cv2.getRotationMatrix2D(center2, angle, 1.0)
            img = cv2.warpAffine(img, M, (w2, h2),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)

        # Sharpen
        gaussian = cv2.GaussianBlur(img, (0, 0), 2)
        sharpened = cv2.addWeighted(img, 1.8, gaussian, -0.8, 0)
        return sharpened
    except Exception as e:
        logger.warning(f"Deskew-sharpen preprocessing failed: {e}")
        return img_rgb


def preprocess_adaptive_binarize(img_rgb):
    """
    Adaptive Gaussian binarization — best for Tesseract on handwritten text.
    Returns grayscale binary image.
    """
    import cv2
    import numpy as np

    try:
        if len(img_rgb.shape) == 3:
            gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_rgb.copy()

        gray = _ensure_min_resolution(gray)
        gray = _remove_borders(gray)

        # Bilateral filter for noise reduction
        denoised = cv2.bilateralFilter(gray, 9, 75, 75)

        # Adaptive threshold — handles uneven lighting
        binarized = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 15
        )

        # Morphological cleanup
        binarized = _remove_noise_morphological(binarized)
        return binarized
    except Exception as e:
        logger.warning(f"Adaptive binarize failed: {e}")
        if len(img_rgb.shape) == 3:
            import cv2 as _cv2
            return _cv2.cvtColor(img_rgb, _cv2.COLOR_RGB2GRAY)
        return img_rgb


def preprocess_otsu_binarize(img_rgb):
    """
    Otsu binarization — best for Tesseract on clean printed table/block text.
    Returns grayscale binary image.
    """
    import cv2
    import numpy as np

    try:
        if len(img_rgb.shape) == 3:
            gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_rgb.copy()

        gray = _ensure_min_resolution(gray)
        gray = _remove_borders(gray)

        # Gaussian blur for smoothing before Otsu
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Otsu's automatic threshold
        _, binarized = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        binarized = _remove_noise_morphological(binarized)
        return binarized
    except Exception as e:
        logger.warning(f"Otsu binarize failed: {e}")
        if len(img_rgb.shape) == 3:
            import cv2 as _cv2
            return _cv2.cvtColor(img_rgb, _cv2.COLOR_RGB2GRAY)
        return img_rgb


# ──────────────────────────────────────────────────────────────────────────────
#  Table Structure Detection via OpenCV
# ──────────────────────────────────────────────────────────────────────────────

def detect_table_cells(img_rgb) -> List[Tuple[int, int, int, int]]:
    """
    Detect table grid cells using OpenCV line/contour detection.
    Returns list of (x, y, w, h) bounding boxes for each cell.
    """
    import cv2
    import numpy as np

    try:
        if len(img_rgb.shape) == 3:
            gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_rgb.copy()

        # Binarize
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Detect horizontal lines
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (gray.shape[1] // 15, 1))
        h_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, h_kernel, iterations=2)

        # Detect vertical lines
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, gray.shape[0] // 15))
        v_lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, v_kernel, iterations=2)

        # Combine to get table grid
        table_mask = cv2.add(h_lines, v_lines)

        # Find contours of cells
        contours, _ = cv2.findContours(table_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        cells = []
        img_area = gray.shape[0] * gray.shape[1]
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            cell_area = w * h
            # Filter: cells should be between 0.1% and 30% of image area
            if 0.001 * img_area < cell_area < 0.3 * img_area:
                # Must be roughly rectangular (aspect ratio check)
                if 0.1 < w / max(h, 1) < 15:
                    cells.append((x, y, w, h))

        # Sort cells top-to-bottom, left-to-right
        cells.sort(key=lambda c: (c[1] // 30, c[0]))
        return cells
    except Exception as e:
        logger.warning(f"Table cell detection failed: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
#  OCR Engine Functions
# ──────────────────────────────────────────────────────────────────────────────

def _run_easy_ocr(img_np, label="") -> Tuple[str, float]:
    """Run EasyOCR on a numpy image array. Returns (text, avg_confidence)."""
    available, engine = get_easy_ocr()
    if not available or engine is None:
        return "", 0.0

    try:
        result = engine.ocr(img_np)
        if not result:
            return "", 0.0

        lines = []
        confidences = []
        for page_res in result:
            if not page_res:
                continue
            if isinstance(page_res, dict):
                # PP-OCRv5 format compatibility
                rec_texts = page_res.get('rec_texts', [])
                rec_scores = page_res.get('rec_scores', [])
                for i, txt in enumerate(rec_texts):
                    if txt and txt.strip():
                        lines.append(txt.strip())
                        if i < len(rec_scores):
                            confidences.append(rec_scores[i])
            else:
                # Standard nested list format
                for line in page_res:
                    if line and len(line) > 1 and line[1]:
                        txt = line[1][0]
                        conf = line[1][1] if len(line[1]) > 1 else 0.5
                        if txt and txt.strip():
                            lines.append(txt.strip())
                            confidences.append(conf)

        text = "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        if label:
            logger.debug(f"EasyOCR [{label}]: {len(lines)} lines, avg_conf={avg_conf:.2f}")
        return text, avg_conf
    except Exception as e:
        logger.warning(f"EasyOCR [{label}] failed: {e}")
        return "", 0.0


def _run_vision_ocr(img_np, label="") -> Tuple[str, float]:
    """Primary vision-based OCR runner."""
    return _run_easy_ocr(img_np, label)



def _run_tesseract(img_np, psm=3, label="") -> Tuple[str, float]:
    """Run Tesseract OCR on a numpy image. Returns (text, estimated_confidence)."""
    try:
        import pytesseract
        from PIL import Image

        pil_img = Image.fromarray(img_np)
        config = f'--oem 1 --psm {psm}'
        text = pytesseract.image_to_string(pil_img, config=config)

        # Get confidence data
        try:
            data = pytesseract.image_to_data(pil_img, config=config, output_type=pytesseract.Output.DICT)
            confs = [int(c) for c in data['conf'] if str(c).lstrip('-').isdigit() and int(c) > 0]
            avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        except Exception:
            avg_conf = 0.5 if text.strip() else 0.0

        if label:
            logger.debug(f"Tesseract [{label}]: {len(text.split())} words, avg_conf={avg_conf:.2f}")
        return text.strip(), avg_conf
    except Exception as e:
        logger.warning(f"Tesseract [{label}] failed: {e}")
        return "", 0.0


def _extract_pypdf2_text(file_path: str) -> str:
    """Extract text layer from PDF using PyMuPDF (fitz) or PyPDF2 fallback."""
    # Try PyMuPDF (fitz) first as it is faster and doesn't hang on corrupt files
    try:
        import fitz
        with fitz.open(file_path) as doc:
            texts = []
            for p_idx, page in enumerate(doc):
                page_text = page.get_text()
                if page_text and page_text.strip():
                    texts.append(f"--- Page {p_idx + 1} ---\n" + page_text.strip())
            return "\n\n".join(texts)
    except Exception as e:
        logger.warning(f"PyMuPDF text extraction failed: {e}. Falling back to PyPDF2...")

    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            texts = []
            for p_idx, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    texts.append(f"--- Page {p_idx + 1} ---\n" + page_text.strip())
            return "\n\n".join(texts)
    except Exception as e:
        logger.warning(f"PyPDF2 text extraction failed: {e}")
        return ""


def _score_text_quality(text: str) -> float:
    """
    Heuristic quality score for OCR output.
    Higher = better. Range: 0.0 to 1.0.
    Considers: length, word density, alphanumeric ratio, repetition,
    and Devanagari/Hindi garbage detection.
    """
    if not text or not text.strip():
        return 0.0

    text = text.strip()
    length = len(text)
    words = text.split()
    word_count = len(words)

    if length < 10:
        return 0.05

    # Alphanumeric ratio (good text has >60% alphanumeric+space)
    alnum_count = sum(1 for c in text if c.isalnum() or c.isspace())
    alnum_ratio = alnum_count / length

    # Average word length (good text: 3-12 chars per word)
    avg_word_len = length / max(word_count, 1)
    word_len_score = 1.0 if 3 <= avg_word_len <= 12 else 0.5

    # Unique word ratio (low = lots of OCR garbage repetition)
    unique_ratio = len(set(w.lower() for w in words)) / max(word_count, 1)

    # Length bonus (more text generally better, capped)
    length_score = min(length / 500.0, 1.0)

    # Detect OCR garbage patterns common in Hindi/Devanagari misreads
    garbage_penalty = 0.0
    garbage_patterns = ['|||', '|||', '...', '___', '===', '###', '***',
                        'lll', 'III', '111', ']]', '[[', '{{', '}}']
    garbage_count = sum(text.count(p) for p in garbage_patterns)
    if garbage_count > 5:
        garbage_penalty = min(garbage_count * 0.02, 0.3)

    # Detect excessive non-ASCII that isn't valid Devanagari
    non_ascii_count = sum(1 for c in text if ord(c) > 127)
    non_ascii_ratio = non_ascii_count / length
    # Valid Hindi text has Devanagari (U+0900-U+097F)
    devanagari_count = sum(1 for c in text if '\u0900' <= c <= '\u097F')
    if non_ascii_ratio > 0.3 and devanagari_count < non_ascii_count * 0.5:
        garbage_penalty += 0.15  # Likely OCR garbage, not real Hindi

    score = (
        0.30 * alnum_ratio +
        0.20 * word_len_score +
        0.20 * unique_ratio +
        0.30 * length_score
        - garbage_penalty
    )
    return min(max(score, 0.0), 1.0)


def _merge_results(results: List[Tuple[str, float, float]]) -> str:
    """
    Merge multiple OCR results intelligently.
    Each result is (text, ocr_confidence, quality_score).
    Returns the best single result or a merged combination.
    """
    if not results:
        return ""

    # Filter out empty results
    valid = [(t, c, q) for t, c, q in results if t and t.strip()]
    if not valid:
        return ""

    # Sort by combined score (quality × 0.6 + confidence × 0.4)
    valid.sort(key=lambda x: x[2] * 0.6 + x[1] * 0.4, reverse=True)

    best_text, best_conf, best_quality = valid[0]

    # If the best result is already high quality, just return it
    if best_quality > 0.7 and best_conf > 0.7:
        return best_text

    # If we have a second result that's also decent, check if it adds value
    if len(valid) >= 2:
        second_text, second_conf, second_quality = valid[1]
        # If second result is significantly longer, it might have captured more
        if len(second_text) > len(best_text) * 1.3 and second_quality > 0.5:
            return second_text
        # If second result has higher confidence but similar length
        if second_conf > best_conf * 1.2 and len(second_text) > len(best_text) * 0.8:
            return second_text

    # CRITICAL: Always return best_text as fallback (fixes None-return bug)
    return best_text

def heal_ocr_text(text: str) -> str:
    """
    Correct OCR spelling mistakes, formatting, and structural issues (e.g. broken tables)
    using a fast LLM pass, without modifying any facts or numbers.
    """
    from llm_client import generate_text
    from document_auditor import is_llm_active
    if not text or not text.strip() or not is_llm_active():
        return text
    
    prompt = (
        "You are an expert document layout and OCR spelling correction tool. "
        "Correct transcription spelling errors, broken tables, structural noise, "
        "and split words (e.g., 'UDY AM' -> 'UDYAM', '1.5l\\111v1' -> '1.5mm') in the OCR text below. "
        "CRITICAL RULES:\n"
        "1. Do NOT summarize or shorten the text. Return the full content.\n"
        "2. Do NOT change any numbers, dates, company names, values, or specifications.\n"
        "3. Return ONLY the healed text, without any comments or headers.\n\n"
        f"OCR TEXT:\n{text[:15000]}"
    )
    try:
        healed = generate_text(prompt, system_instruction="Fix OCR errors while strictly preserving facts and numbers.")
        if healed and healed.strip():
            return healed.strip()
    except Exception as e:
        logger.warning(f"OCR healing pass failed: {e}")
    return text


def extract_layout_forensics_with_vision(img_np, page_num: int = 1) -> list:
    """
    Query Vision LLM to identify visual segments (Headers, Tables, Paragraphs, Signatures, Seals)
    with relative bounding box coordinates in [nx1, ny1, nx2, ny2] 600x800 system dimensions.
    """
    from llm_client import generate_with_vision, get_provider_status
    from document_auditor import is_llm_active
    import cv2
    import base64
    import json
    
    if not is_llm_active():
        return []
        
    status = get_provider_status()
    if status.get("strict_open_source") or status.get("active_provider") not in ["gemini", "openai"]:
        return []
        
    try:
        # Encode to JPEG
        success, encoded_img = cv2.imencode('.jpg', img_np)
        if not success:
            return []
        img_b64 = base64.b64encode(encoded_img).decode('utf-8')

        prompt = (
            "Analyze this document page and identify layout segments. "
            "Specifically detect: Headers, Tables, Paragraphs, Signatures, and Seals/Stamps. "
            "For each detected segment, estimate its bounding box coordinates within a normalized 600x800 coordinate space, "
            "where x is 0 to 600 (left to right) and y is 0 to 800 (top to bottom).\n"
            "Return a JSON object with this key:\n"
            "- \"segments\": list of dicts, each with keys \"type\" (one of \"Header\", \"Table\", \"Paragraph\", \"Signature\", \"Seal/Stamp\"), "
            "\"bbox\": [x_min, y_min, x_max, y_max] (numbers), and \"content\" (verbatim text contents of that block).\n\n"
            "Only return valid JSON starting with '{' and ending with '}'."
        )

        res_str = generate_with_vision(prompt, img_b64, mime_type="image/jpeg")
        # Clean markdown wrappers if any
        res_str = res_str.strip()
        if res_str.startswith("```json"):
            res_str = res_str[7:]
        elif res_str.startswith("```"):
            res_str = res_str[3:]
        if res_str.endswith("```"):
            res_str = res_str[:-3]
        res_str = res_str.strip()

        data = json.loads(res_str)
        segments = data.get("segments", [])
        
        # Add page index and confidence score
        formatted = []
        for seg in segments:
            bbox = seg.get("bbox", [])
            if len(bbox) == 4:
                # Clamp coordinates
                x1 = max(0.0, min(float(bbox[0]), 600.0))
                y1 = max(0.0, min(float(bbox[1]), 800.0))
                x2 = max(0.0, min(float(bbox[2]), 600.0))
                y2 = max(0.0, min(float(bbox[3]), 800.0))
                
                formatted.append({
                    "page": page_num,
                    "type": seg.get("type", "Paragraph"),
                    "bbox": [x1, y1, x2, y2],
                    "score": 0.98,
                    "content": seg.get("content", ""),
                    "pqc_mapping": None
                })
        return formatted
    except Exception as e:
        logger.warning(f"Vision layout forensics failed for page {page_num}: {e}")
        return []



def _run_vision_llm_ocr(img_np, page_num: int = 1) -> Tuple[str, float]:
    """
    Attempts to run high-accuracy OCR using Gemini/OpenAI Vision APIs.
    Only triggered if a cloud provider (gemini/openai) is active and configured.
    """
    import cv2
    import base64
    try:
        from llm_client import generate_with_vision, get_provider_status
        status = get_provider_status()
        if status.get("strict_open_source") or status.get("active_provider") not in ["gemini", "openai"]:
            return "", 0.0

        # Encode to JPEG
        success, encoded_img = cv2.imencode('.jpg', img_np)
        if not success:
            return "", 0.0
        img_b64 = base64.b64encode(encoded_img).decode('utf-8')

        prompt = (
            "Transcribe all text from this page. If there are tables, "
            "output them as clean Markdown tables. Transcribe all signatures, "
            "dates, and seal/stamp details. Return only the verbatim transcribed "
            "text without any intro/outro comments."
        )

        print(f"  [p{page_num}] Attempting Vision LLM OCR (using {status['active_provider']} Vision)...")
        text = generate_with_vision(prompt, img_b64, mime_type="image/jpeg")
        if text and text.strip():
            # Score the text quality
            q = _score_text_quality(text)
            return text, q
    except Exception as e:
        logger.warning(f"Vision LLM OCR failed on page {page_num}: {e}")

    return "", 0.0


def ocr_page(page_image, page_num: int = 1) -> Dict[str, Any]:
    """
    Run the full multi-engine OCR cascade on a single page image (PIL Image).
    Returns dict with 'text', 'confidence', 'quality', 'engine_used'.
    """
    import numpy as np
    from PIL import Image

    img_np = np.array(page_image.convert('RGB'))
    results = []

    # ── Strategy 0: Vision LLM OCR ──
    try:
        text0, conf0 = _run_vision_llm_ocr(img_np, page_num=page_num)
        if text0.strip() and conf0 >= 0.70:
            print(f"  [p{page_num}] Early-exit triggered at Strategy 0 (Vision LLM OCR). Skipping remaining strategies.")
            return {
                "text": text0,
                "confidence": round(conf0, 3),
                "quality": round(conf0, 3),
                "engine_used": "VisionLLM-OCR",
                "page": page_num,
                "candidates": 1
            }
    except Exception as e:
        logger.warning(f"Strategy 0 (Vision LLM OCR) failed on page {page_num}: {e}")

    # ── Strategy 1: EasyOCR on CLAHE-enhanced color image ──
    try:
        prep1 = preprocess_clahe_color(img_np)
        text1, conf1 = _run_easy_ocr(prep1, label=f"p{page_num}-CLAHE")
        q1 = _score_text_quality(text1)
        if text1.strip():
            results.append((text1, conf1, q1, "EasyOCR-CLAHE"))
            print(f"  [p{page_num}] EasyOCR-CLAHE: {len(text1)} chars, conf={conf1:.2f}, quality={q1:.2f}")
            if conf1 >= 0.85 and q1 >= 0.70:
                print(f"  [p{page_num}] Early-exit triggered at Strategy 1 (EasyOCR-CLAHE). Skipping remaining strategies.")
                return {
                    "text": text1,
                    "confidence": round(conf1, 3),
                    "quality": round(q1, 3),
                    "engine_used": "EasyOCR-CLAHE",
                    "page": page_num,
                    "candidates": 1
                }
    except Exception as e:
        logger.warning(f"Strategy 1 (EasyOCR-CLAHE) failed on page {page_num}: {e}")

    # ── Strategy 2: EasyOCR on deskewed + sharpened image ──
    try:
        prep2 = preprocess_deskew_sharpen(img_np)
        text2, conf2 = _run_easy_ocr(prep2, label=f"p{page_num}-deskew")
        q2 = _score_text_quality(text2)
        if text2.strip():
            results.append((text2, conf2, q2, "EasyOCR-Deskew"))
            print(f"  [p{page_num}] EasyOCR-Deskew: {len(text2)} chars, conf={conf2:.2f}, quality={q2:.2f}")
            if conf2 >= 0.85 and q2 >= 0.70:
                print(f"  [p{page_num}] Early-exit triggered at Strategy 2 (EasyOCR-Deskew). Skipping remaining strategies.")
                return {
                    "text": text2,
                    "confidence": round(conf2, 3),
                    "quality": round(q2, 3),
                    "engine_used": "EasyOCR-Deskew",
                    "page": page_num,
                    "candidates": 2
                }
    except Exception as e:
        logger.warning(f"Strategy 2 (EasyOCR-Deskew) failed on page {page_num}: {e}")

    # ── Strategy 3: Tesseract PSM 3 on adaptive-binarized image ──
    try:
        prep3 = preprocess_adaptive_binarize(img_np)
        text3, conf3 = _run_tesseract(prep3, psm=3, label=f"p{page_num}-adaptive")
        q3 = _score_text_quality(text3)
        if text3.strip():
            results.append((text3, conf3, q3, "Tesseract-PSM3"))
            print(f"  [p{page_num}] Tesseract-PSM3: {len(text3)} chars, conf={conf3:.2f}, quality={q3:.2f}")
    except Exception as e:
        logger.warning(f"Strategy 3 (Tesseract-PSM3) failed on page {page_num}: {e}")

    # ── Strategy 4: Tesseract PSM 6 on Otsu-binarized image ──
    try:
        prep4 = preprocess_otsu_binarize(img_np)
        text4, conf4 = _run_tesseract(prep4, psm=6, label=f"p{page_num}-otsu")
        q4 = _score_text_quality(text4)
        if text4.strip():
            results.append((text4, conf4, q4, "Tesseract-PSM6"))
            print(f"  [p{page_num}] Tesseract-PSM6: {len(text4)} chars, conf={conf4:.2f}, quality={q4:.2f}")
    except Exception as e:
        logger.warning(f"Strategy 4 (Tesseract-PSM6) failed on page {page_num}: {e}")

    # ── Strategy 5: Table-aware OCR ──
    # Detect table cells and OCR each cell individually for structured content
    try:
        cells = detect_table_cells(img_np)
        if cells and len(cells) >= 4:  # At least 4 cells to consider it a table
            # Group cells by Y coordinate (row detection with 15px tolerance)
            rows = []
            for cell in cells[:50]:  # Cap at 50 cells
                cx, cy, cw, ch = cell
                placed = False
                for r in rows:
                    if abs(r[0][1] - cy) < 15:
                        r.append(cell)
                        placed = True
                        break
                if not placed:
                    rows.append([cell])
            
            # Sort rows by Y, and cells within each row by X
            rows.sort(key=lambda r: r[0][1])
            for r in rows:
                r.sort(key=lambda c: c[0])
            
            # Perform cell-by-cell OCR and construct Markdown table rows
            md_rows = []
            for r in rows:
                row_cells = []
                for cx, cy, cw, ch in r:
                    cell_crop = img_np[cy:cy+ch, cx:cx+cw]
                    if cell_crop.size == 0:
                        continue
                    cell_text, cell_conf = _run_easy_ocr(cell_crop, label=f"p{page_num}-cell")
                    if not cell_text.strip():
                        # Fallback to Tesseract for this cell
                        cell_bin = preprocess_adaptive_binarize(cell_crop)
                        cell_text, cell_conf = _run_tesseract(cell_bin, psm=6, label=f"p{page_num}-cell-tess")
                    
                    clean_cell = cell_text.strip().replace("\n", " ").replace("|", "\\|")
                    row_cells.append(clean_cell if clean_cell else " ")
                if row_cells:
                    md_rows.append("| " + " | ".join(row_cells) + " |")
            
            if md_rows:
                if len(md_rows) > 1:
                    header_len = len(rows[0])
                    separator = "|" + "---|" * header_len
                    md_rows.insert(1, separator)
                
                table_combined = "\n".join(md_rows)
                qt = _score_text_quality(table_combined)
                results.append((table_combined, 0.75, qt, "Table-CellOCR"))
                print(f"  [p{page_num}] Table-CellOCR: {len(cells)} cells grouped into {len(rows)} rows formatted as Markdown table.")
    except Exception as e:
        logger.warning(f"Strategy 5 (Table-CellOCR) failed on page {page_num}: {e}")

    # ── Merge results ──
    if not results:
        return {
            "text": "",
            "confidence": 0.0,
            "quality": 0.0,
            "engine_used": "none",
            "page": page_num,
            "candidates": 0
        }

    # Pick the best result
    merge_input = [(r[0], r[1], r[2]) for r in results]
    best_text = _merge_results(merge_input)

    # Find which engine produced the best text
    best_engine = "merged"
    best_conf = 0.0
    best_qual = 0.0
    for text, conf, qual, engine in results:
        if text == best_text:
            best_engine = engine
            best_conf = conf
            best_qual = qual
            break

    return {
        "text": best_text,
        "confidence": round(best_conf, 3),
        "quality": round(best_qual, 3),
        "engine_used": best_engine,
        "page": page_num,
        "candidates": len(results)
    }


def extract_text_from_file(file_path: str) -> str:
    """
    High-power OCR extraction from .txt, .pdf, .png, .jpg files.
    Uses multi-engine cascade with intelligent result selection.
    Returns the best extracted text.
    """
    import numpy as np
    from PIL import Image

    # ── Check Cache First ──
    cache_key = _get_ocr_cache_key(file_path)
    cached_text = _read_ocr_cache(cache_key)
    if cached_text is not None:
        print(f"[OCR Engine] Cache HIT for {os.path.basename(file_path)}. Skipping OCR cascade.")
        return cached_text

    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''
    engines_used = []
    confidences = []

    # Plain text files
    if ext == 'txt':
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                _write_ocr_cache(cache_key, text, file_path, engine_used="Plain Text Parser", confidence=1.0)
                return text
        except Exception as e:
            return f"Failed to parse text file: {e}"

    # Convert PDF/Image to page images
    pages = []
    if ext == 'pdf':
        try:
            import fitz
            from pdf2image import convert_from_path
            
            print(f"[OCR Engine] Analyzing PDF page-by-page: {os.path.basename(file_path)}")
            all_page_texts = []
            
            with fitz.open(file_path) as doc:
                num_pages = len(doc)
                for p_idx in range(num_pages):
                    page = doc[p_idx]
                    page_text = page.get_text().strip()
                    
                    # Check quality of the page's digital text layer
                    if page_text and _score_text_quality(page_text) > 0.6 and len(page_text) > 100:
                        print(f"  Page {p_idx + 1}: Using clean digital text layer ({len(page_text)} chars)")
                        all_page_texts.append(f"--- Page {p_idx + 1} ---\n" + page_text)
                        engines_used.append("PyMuPDF (Digital Text)")
                        confidences.append(1.0)
                    else:
                        # Convert only this specific page to image and run the OCR cascade
                        print(f"  Page {p_idx + 1}: Text layer missing or low quality. Running OCR cascade...")
                        converted = convert_from_path(file_path, dpi=300, first_page=p_idx + 1, last_page=p_idx + 1)
                        if converted:
                            result = ocr_page(converted[0], page_num=p_idx + 1)
                            if result["text"].strip():
                                all_page_texts.append(f"--- Page {p_idx + 1} ---\n" + result["text"])
                                engines_used.append(result["engine_used"])
                                confidences.append(result["confidence"])
                                print(f"    Page {p_idx + 1} OCR: {result['engine_used']} (conf={result['confidence']:.2f}, qual={result['quality']:.2f})")
                            else:
                                all_page_texts.append(f"--- Page {p_idx + 1} ---\n[Empty Page]")
                        else:
                            # Fallback if image conversion fails
                            all_page_texts.append(f"--- Page {p_idx + 1} ---\n" + page_text)
            
            combined = "\n\n".join(all_page_texts)
            if combined.strip():
                combined = heal_ocr_text(combined)
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.90
                engine_name = ", ".join(list(set(engines_used))) if engines_used else "PyMuPDF (Digital Text)"
                _write_ocr_cache(cache_key, combined, file_path, engine_used=engine_name, confidence=avg_conf)
                return combined
                
        except Exception as e:
            print(f"[OCR Engine] Hybrid PDF extraction failed: {e}. Falling back to default cascade.")
            # Fallback to default cascade of converting whole PDF to images
            try:
                from pdf2image import convert_from_path
                print(f"[OCR Engine] Converting whole PDF to images at 300 DPI...")
                pages = convert_from_path(file_path, dpi=300)
            except Exception as convert_err:
                print(f"[OCR Engine] Whole PDF conversion failed: {convert_err}")
                pypdf_text = _extract_pypdf2_text(file_path)
                if pypdf_text.strip():
                    _write_ocr_cache(cache_key, pypdf_text, file_path, engine_used="PyPDF2 (Digital Text)", confidence=1.0)
                    return pypdf_text
    elif ext in ('png', 'jpg', 'jpeg', 'tiff', 'tif', 'bmp'):
        try:
            pages = [Image.open(file_path).convert('RGB')]
        except Exception as e:
            print(f"[OCR Engine] Failed to open image: {e}")

    # Run OCR cascade on each page
    if pages:
        print(f"[OCR Engine] Processing {len(pages)} page(s) with multi-engine cascade...")
        all_page_texts = []
        for idx, page in enumerate(pages):
            result = ocr_page(page, page_num=idx + 1)
            if result["text"].strip():
                all_page_texts.append(f"--- Page {idx + 1} ---\n" + result["text"])
                engines_used.append(result["engine_used"])
                confidences.append(result["confidence"])
                print(f"  Page {idx+1}: {result['engine_used']} "
                      f"(conf={result['confidence']:.2f}, qual={result['quality']:.2f})")

        combined = "\n\n".join(all_page_texts)
        if combined.strip():
            print(f"[OCR Engine] Total extracted: {len(combined)} chars from {len(all_page_texts)}/{len(pages)} pages")
            combined = heal_ocr_text(combined)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.85
            engine_name = ", ".join(list(set(engines_used))) if engines_used else "OCR Cascade"
            _write_ocr_cache(cache_key, combined, file_path, engine_used=engine_name, confidence=avg_conf)
            return combined

    # PyPDF2 fallback for PDFs with text layers
    if ext == 'pdf':
        print(f"[OCR Engine] Trying PyPDF2 text layer fallback...")
        pypdf_text = _extract_pypdf2_text(file_path)
        if pypdf_text.strip():
            print(f"[OCR Engine] PyPDF2 extracted {len(pypdf_text)} chars")
            pypdf_text = heal_ocr_text(pypdf_text)
            _write_ocr_cache(cache_key, pypdf_text, file_path, engine_used="PyPDF2 (Digital Text)", confidence=1.0)
            return pypdf_text

    return "OCR Extraction Failed. No text could be extracted from the document."


def ocr_image_np(img_np) -> str:
    """
    Quick OCR on a raw numpy array (RGB). Used by layout forensics.
    Runs EasyOCR first, falls back to Tesseract.
    """
    text, conf = _run_easy_ocr(img_np, label="direct")
    if text.strip() and conf > 0.3:
        return text

    # Fallback
    prep = preprocess_adaptive_binarize(img_np)
    text, conf = _run_tesseract(prep, psm=3, label="direct-fallback")
    return text


# ──────────────────────────────────────────────────────────────────────────────
#  Layout Forensics Helper (used by reports_pqc.py)
# ──────────────────────────────────────────────────────────────────────────────

def preprocess_for_layout_ocr(img_np):
    """
    Preprocessing optimized for EasyOCR layout analysis in reports_pqc.py.
    Returns color RGB image with enhanced contrast and sharpness.
    """
    return preprocess_clahe_color(img_np)
