"""
GEM Vision Forensics Engine v4.0
- Error Level Analysis (single & multi-quality)
- EXIF metadata forensic analysis
- Copy-move detection via DCT block matching
- Comprehensive forensic scan orchestrator
"""
import os
import io
import math
import base64
import struct
from datetime import datetime
from typing import Optional, List, Dict, Any

from PIL import Image, ImageChops, ImageEnhance

# Optional imports for advanced features
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# ─────────────────────────────────────────────────────────────────
#  ERROR LEVEL ANALYSIS (Original — preserved for backward compat)
# ─────────────────────────────────────────────────────────────────
def perform_ela(image_bytes: bytes, quality: int = 90) -> dict:
    """
    Performs Error Level Analysis (ELA) on an image to detect digital tampering.
    Returns the ELA image bytes (heatmap) and a forgery risk score.
    """
    try:
        # Load original image
        original = Image.open(io.BytesIO(image_bytes)).convert('RGB')

        # Save it to a temporary buffer at a known quality
        temp_buffer = io.BytesIO()
        original.save(temp_buffer, 'JPEG', quality=quality)
        temp_buffer.seek(0)

        # Open the resaved image
        resaved = Image.open(temp_buffer)

        # Calculate the absolute difference between original and resaved
        ela_image = ImageChops.difference(original, resaved)

        # Get the extrema (min, max differences) to scale the brightness
        extrema = ela_image.getextrema()
        max_diff = max([ex[1] for ex in extrema])
        if max_diff == 0:
            max_diff = 1

        # Scale the image to make the ELA differences visible
        scale = 255.0 / max_diff
        ela_image = ImageEnhance.Brightness(ela_image).enhance(scale)

        # Calculate a forgery risk score based on variance of differences
        stat = ImageChops.difference(original, resaved)
        stat_data = stat.getdata()

        diff_sum = 0
        diff_sq_sum = 0
        count = len(stat_data)

        for pixel in stat_data:
            avg = sum(pixel) / 3.0
            diff_sum += avg
            diff_sq_sum += avg * avg

        mean = diff_sum / count
        variance = (diff_sq_sum / count) - (mean * mean)
        std_dev = math.sqrt(max(0, variance))

        # Normalized score (0-100)
        risk_score = min(100.0, max(0.0, (std_dev - 2) * 15))

        if risk_score > 70:
            verdict = "CRITICAL: Forgery Detected"
        elif risk_score > 40:
            verdict = "WARNING: Potential Alteration"
        else:
            verdict = "NORMAL: No Tampering Detected"

        # Save ELA image to bytes
        out_buffer = io.BytesIO()
        ela_image.save(out_buffer, format="JPEG", quality=90)
        ela_bytes = out_buffer.getvalue()
        b64_image = base64.b64encode(ela_bytes).decode('utf-8')

        return {
            "success": True,
            "risk_score": round(risk_score, 1),
            "std_dev": round(std_dev, 2),
            "verdict": verdict,
            "ela_base64": b64_image
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ─────────────────────────────────────────────────────────────────
#  HELPER: Convert to JPEG bytes for ELA processing
# ─────────────────────────────────────────────────────────────────
def _ensure_jpeg_bytes(image_input) -> bytes:
    """
    Accept file path (str) or bytes; return JPEG bytes.
    Converts non-JPEG formats (PNG, BMP, TIFF, etc.) to JPEG.
    """
    if isinstance(image_input, str):
        with open(image_input, "rb") as f:
            raw_bytes = f.read()
    elif isinstance(image_input, bytes):
        raw_bytes = image_input
    else:
        raise ValueError(f"Expected file path or bytes, got {type(image_input)}")

    # Try to detect format; convert to JPEG if necessary
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.format and img.format.upper() == "JPEG":
            return raw_bytes
        # Convert to JPEG
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=95)
        return buf.getvalue()
    except Exception:
        # If we can't even open it, return raw and let downstream handle errors
        return raw_bytes


def _compute_ela_stats(original: Image.Image, quality: int) -> dict:
    """
    Internal ELA computation at a given quality level.
    Returns std_dev, mean_diff, risk_score, and the ELA PIL image.
    """
    temp_buffer = io.BytesIO()
    original.save(temp_buffer, 'JPEG', quality=quality)
    temp_buffer.seek(0)
    resaved = Image.open(temp_buffer)

    diff_img = ImageChops.difference(original, resaved)
    stat_data = diff_img.getdata()

    diff_sum = 0.0
    diff_sq_sum = 0.0
    count = len(stat_data)

    for pixel in stat_data:
        avg = sum(pixel) / 3.0
        diff_sum += avg
        diff_sq_sum += avg * avg

    mean_diff = diff_sum / max(count, 1)
    variance = (diff_sq_sum / max(count, 1)) - (mean_diff * mean_diff)
    std_dev = math.sqrt(max(0, variance))

    # Normalize risk score: std_dev < 2 → low, > 8 → high
    risk_score = min(100.0, max(0.0, (std_dev - 2) * 15))

    # Enhance ELA image for visualization
    extrema = diff_img.getextrema()
    max_diff_val = max([ex[1] for ex in extrema])
    if max_diff_val == 0:
        max_diff_val = 1
    ela_enhanced = ImageEnhance.Brightness(diff_img).enhance(255.0 / max_diff_val)

    return {
        "std_dev": std_dev,
        "mean_diff": mean_diff,
        "risk_score": risk_score,
        "ela_image": ela_enhanced,
    }


# ─────────────────────────────────────────────────────────────────
#  MULTI-QUALITY ELA
# ─────────────────────────────────────────────────────────────────
def multi_quality_ela(image_path: str) -> dict:
    """
    Runs Error Level Analysis at multiple JPEG quality levels [90, 75, 50]
    to improve detection sensitivity across different compression artifacts.

    Args:
        image_path: Path to the image file.

    Returns:
        dict with:
            - composite_score (float, 0-100): weighted average across levels
            - per_level (list[dict]): per-quality-level breakdown
            - verdict (str): overall tampering verdict
            - ela_base64 (str): best ELA heatmap as base64 JPEG
    """
    quality_levels = [90, 75, 50]
    # Weights: lower quality ELA amplifies manipulation, but also noise
    quality_weights = {90: 0.45, 75: 0.35, 50: 0.20}

    try:
        jpeg_bytes = _ensure_jpeg_bytes(image_path)
        original = Image.open(io.BytesIO(jpeg_bytes)).convert('RGB')

        per_level = []
        weighted_score_sum = 0.0
        weight_sum = 0.0
        best_ela_image = None
        best_score = -1.0

        for q in quality_levels:
            stats = _compute_ela_stats(original, q)
            w = quality_weights[q]
            weighted_score_sum += stats["risk_score"] * w
            weight_sum += w

            level_result = {
                "quality": q,
                "risk_score": round(stats["risk_score"], 2),
                "std_dev": round(stats["std_dev"], 3),
                "mean_diff": round(stats["mean_diff"], 3),
                "weight": w,
            }
            per_level.append(level_result)

            # Track best ELA for output (highest risk score level)
            if stats["risk_score"] > best_score:
                best_score = stats["risk_score"]
                best_ela_image = stats["ela_image"]

        composite_score = round(weighted_score_sum / max(weight_sum, 1e-9), 2)

        # Encode best ELA heatmap
        ela_b64 = ""
        if best_ela_image:
            buf = io.BytesIO()
            best_ela_image.save(buf, format="JPEG", quality=90)
            ela_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        if composite_score > 70:
            verdict = "CRITICAL: Strong evidence of digital manipulation"
        elif composite_score > 40:
            verdict = "WARNING: Potential alteration detected at multiple quality levels"
        elif composite_score > 20:
            verdict = "CAUTION: Minor anomalies detected, may warrant review"
        else:
            verdict = "NORMAL: No significant tampering indicators"

        return {
            "success": True,
            "composite_score": composite_score,
            "per_level": per_level,
            "verdict": verdict,
            "ela_base64": ela_b64,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────
#  EXIF METADATA FORENSIC ANALYSIS
# ─────────────────────────────────────────────────────────────────
def analyze_exif_metadata(image_path: str) -> dict:
    """
    Extracts and analyzes EXIF metadata from an image for forensic indicators.

    Checks for:
        - Software editing signatures (Photoshop, GIMP, Lightroom, etc.)
        - Date inconsistencies (creation vs modification vs digitized)
        - GPS data presence (location embedding)
        - Thumbnail inconsistencies (thumbnail dimensions vs main image)

    Args:
        image_path: Path to the image file.

    Returns:
        dict with extracted EXIF fields, risk indicators, and overall metadata risk score.
    """
    result = {
        "success": True,
        "has_exif": False,
        "risk_indicators": [],
        "metadata_risk_score": 0.0,
        "exif_fields": {},
        "software_detected": None,
        "date_analysis": {},
        "gps_present": False,
        "thumbnail_analysis": {},
    }

    try:
        img = Image.open(image_path)
    except Exception as e:
        return {"success": False, "error": f"Cannot open image: {e}"}

    # Extract EXIF data
    exif_data = {}
    try:
        raw_exif = img._getexif()
        if raw_exif is None:
            result["has_exif"] = False
            return result
        # Map EXIF tag IDs to names
        from PIL.ExifTags import TAGS, GPSTAGS
        for tag_id, value in raw_exif.items():
            tag_name = TAGS.get(tag_id, str(tag_id))
            # Convert bytes to string for JSON serialization
            if isinstance(value, bytes):
                try:
                    value = value.decode('utf-8', errors='replace')
                except Exception:
                    value = repr(value)
            elif isinstance(value, tuple) and len(value) > 10:
                value = str(value)[:200]
            exif_data[tag_name] = value
        result["has_exif"] = True
        result["exif_fields"] = {k: str(v)[:500] for k, v in exif_data.items()}
    except Exception as e:
        result["has_exif"] = False
        result["exif_fields"] = {"error": str(e)}
        return result

    risk_score = 0.0
    indicators = []

    # ── Check 1: Software editing signatures ────────────────────
    editing_software = [
        "photoshop", "gimp", "lightroom", "affinity", "paint.net",
        "pixlr", "corel", "illustrator", "inkscape", "snapseed",
        "canva", "fotor", "picmonkey", "acdsee",
    ]
    software_field = str(exif_data.get("Software", "")).lower()
    processing_field = str(exif_data.get("ProcessingSoftware", "")).lower()
    image_description = str(exif_data.get("ImageDescription", "")).lower()
    combined_sw = f"{software_field} {processing_field} {image_description}"

    detected_editor = None
    for editor in editing_software:
        if editor in combined_sw:
            detected_editor = editor.title()
            break

    if detected_editor:
        risk_score += 35
        indicators.append({
            "type": "SOFTWARE_EDITING",
            "severity": "HIGH",
            "detail": f"Image processed with editing software: {detected_editor}",
            "field_value": exif_data.get("Software", exif_data.get("ProcessingSoftware", "N/A")),
        })
        result["software_detected"] = detected_editor
    elif software_field and software_field != "none":
        result["software_detected"] = str(exif_data.get("Software", ""))

    # ── Check 2: Date inconsistencies ───────────────────────────
    date_fields = {
        "DateTimeOriginal": exif_data.get("DateTimeOriginal"),
        "DateTimeDigitized": exif_data.get("DateTimeDigitized"),
        "DateTime": exif_data.get("DateTime"),
    }
    parsed_dates = {}
    date_formats = ["%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]
    for field_name, date_str in date_fields.items():
        if date_str:
            for fmt in date_formats:
                try:
                    parsed_dates[field_name] = datetime.strptime(str(date_str).strip(), fmt)
                    break
                except (ValueError, TypeError):
                    continue

    result["date_analysis"] = {
        "fields_found": {k: str(v) for k, v in date_fields.items() if v},
        "parsed_count": len(parsed_dates),
    }

    if len(parsed_dates) >= 2:
        date_values = list(parsed_dates.values())
        date_keys = list(parsed_dates.keys())
        for i in range(len(date_values)):
            for j in range(i + 1, len(date_values)):
                diff = abs((date_values[i] - date_values[j]).total_seconds())
                if diff > 86400:  # More than 1 day difference
                    days_diff = diff / 86400
                    risk_score += 25
                    indicators.append({
                        "type": "DATE_INCONSISTENCY",
                        "severity": "HIGH",
                        "detail": (
                            f"Date mismatch: {date_keys[i]} vs {date_keys[j]} "
                            f"differ by {days_diff:.1f} days"
                        ),
                        "dates": {
                            date_keys[i]: str(date_values[i]),
                            date_keys[j]: str(date_values[j]),
                        },
                    })
                    break  # One inconsistency is enough
            else:
                continue
            break

    # ── Check 3: GPS data presence ──────────────────────────────
    gps_info = exif_data.get("GPSInfo")
    if gps_info:
        result["gps_present"] = True
        risk_score += 10
        indicators.append({
            "type": "GPS_DATA_PRESENT",
            "severity": "LOW",
            "detail": "Image contains GPS geolocation data — privacy/provenance indicator",
        })

    # ── Check 4: Thumbnail inconsistencies ──────────────────────
    try:
        main_size = img.size  # (width, height)
        main_ratio = main_size[0] / max(main_size[1], 1)

        # Check for embedded thumbnail
        thumb_data = exif_data.get("JPEGThumbnail") or exif_data.get("TIFFThumbnail")
        thumb_width = exif_data.get("ThumbnailImageWidth") or exif_data.get("ImageWidth")
        thumb_height = exif_data.get("ThumbnailImageHeight") or exif_data.get("ImageLength")

        if thumb_data and isinstance(thumb_data, (str, bytes)):
            try:
                if isinstance(thumb_data, str):
                    thumb_img = Image.open(io.BytesIO(thumb_data.encode('latin-1')))
                else:
                    thumb_img = Image.open(io.BytesIO(thumb_data))
                thumb_size = thumb_img.size
                thumb_ratio = thumb_size[0] / max(thumb_size[1], 1)
                ratio_diff = abs(main_ratio - thumb_ratio)
                result["thumbnail_analysis"] = {
                    "main_size": list(main_size),
                    "thumbnail_size": list(thumb_size),
                    "aspect_ratio_diff": round(ratio_diff, 4),
                }
                if ratio_diff > 0.15:
                    risk_score += 20
                    indicators.append({
                        "type": "THUMBNAIL_MISMATCH",
                        "severity": "MODERATE",
                        "detail": (
                            f"Thumbnail aspect ratio ({thumb_ratio:.3f}) differs significantly "
                            f"from main image ({main_ratio:.3f}). Possible crop/edit."
                        ),
                    })
            except Exception:
                pass
    except Exception:
        pass

    # Normalize risk score to 0-100
    result["metadata_risk_score"] = round(min(100.0, risk_score), 2)
    result["risk_indicators"] = indicators

    return result


# ─────────────────────────────────────────────────────────────────
#  COPY-MOVE DETECTION (DCT Block Matching)
# ─────────────────────────────────────────────────────────────────
def detect_copy_move(image_path: str, block_size: int = 16, similarity_threshold: float = 0.95,
                     min_distance: int = 32) -> dict:
    """
    Detect copy-move forgery using block-based DCT coefficient matching.

    Divides the image into non-overlapping blocks, computes DCT coefficients
    for each block, and finds similar blocks that are spatially distant.

    Args:
        image_path: Path to the image file.
        block_size: Size of square blocks (default 16x16).
        similarity_threshold: Cosine similarity threshold (default 0.95).
        min_distance: Minimum pixel distance between matched blocks (default 32).

    Returns:
        dict with suspicious region pairs, their coordinates, and detection score.
    """
    if not HAS_NUMPY:
        return {
            "success": False,
            "error": "numpy is required for copy-move detection. Install with: pip install numpy",
        }

    try:
        img = Image.open(image_path).convert('L')  # Grayscale for DCT
        img_array = np.array(img, dtype=np.float64)
        h, w = img_array.shape

        # Ensure image is large enough
        if h < block_size * 3 or w < block_size * 3:
            return {
                "success": True,
                "suspicious_pairs": [],
                "detection_score": 0.0,
                "verdict": "Image too small for block-based copy-move detection",
                "blocks_analyzed": 0,
            }

        # Divide into non-overlapping blocks
        rows = h // block_size
        cols = w // block_size
        blocks = []
        block_coords = []

        for r in range(rows):
            for c in range(cols):
                y1, y2 = r * block_size, (r + 1) * block_size
                x1, x2 = c * block_size, (c + 1) * block_size
                block = img_array[y1:y2, x1:x2]
                blocks.append(block)
                block_coords.append((x1, y1, x2, y2))

        if len(blocks) < 4:
            return {
                "success": True,
                "suspicious_pairs": [],
                "detection_score": 0.0,
                "verdict": "Too few blocks for analysis",
                "blocks_analyzed": len(blocks),
            }

        # Compute DCT-like features using mean + variance per sub-block quadrant
        # (Lightweight approximation of DCT for speed without scipy.fftpack)
        features = []
        for block in blocks:
            half = block_size // 2
            q1 = block[:half, :half]
            q2 = block[:half, half:]
            q3 = block[half:, :half]
            q4 = block[half:, half:]
            feat = np.array([
                q1.mean(), q1.std(),
                q2.mean(), q2.std(),
                q3.mean(), q3.std(),
                q4.mean(), q4.std(),
                block.mean(), block.std(),
                np.median(block),
                float(np.percentile(block, 25)),
                float(np.percentile(block, 75)),
            ])
            features.append(feat)

        features = np.array(features)

        # Normalize features for cosine similarity
        norms = np.linalg.norm(features, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        features_norm = features / norms

        # Find similar block pairs
        suspicious_pairs = []
        n_blocks = len(features_norm)

        # For efficiency, limit comparison scope for large images
        max_comparisons = min(n_blocks, 500)
        # Use random sampling for very large images
        if n_blocks > max_comparisons:
            indices = np.random.RandomState(42).choice(n_blocks, max_comparisons, replace=False)
        else:
            indices = np.arange(n_blocks)

        for i_idx in range(len(indices)):
            i = indices[i_idx]
            for j_idx in range(i_idx + 1, len(indices)):
                j = indices[j_idx]
                # Compute spatial distance between block centers
                cx_i = (block_coords[i][0] + block_coords[i][2]) / 2
                cy_i = (block_coords[i][1] + block_coords[i][3]) / 2
                cx_j = (block_coords[j][0] + block_coords[j][2]) / 2
                cy_j = (block_coords[j][1] + block_coords[j][3]) / 2
                dist = math.sqrt((cx_i - cx_j) ** 2 + (cy_i - cy_j) ** 2)

                if dist < min_distance:
                    continue  # Skip adjacent blocks

                # Cosine similarity
                sim = float(np.dot(features_norm[i], features_norm[j]))

                if sim >= similarity_threshold:
                    suspicious_pairs.append({
                        "block_a": {
                            "x1": int(block_coords[i][0]), "y1": int(block_coords[i][1]),
                            "x2": int(block_coords[i][2]), "y2": int(block_coords[i][3]),
                        },
                        "block_b": {
                            "x1": int(block_coords[j][0]), "y1": int(block_coords[j][1]),
                            "x2": int(block_coords[j][2]), "y2": int(block_coords[j][3]),
                        },
                        "similarity": round(sim, 4),
                        "distance_px": round(dist, 1),
                    })

        # Cap results
        suspicious_pairs.sort(key=lambda p: p["similarity"], reverse=True)
        suspicious_pairs = suspicious_pairs[:50]

        # Detection score based on number and quality of matches
        if suspicious_pairs:
            avg_sim = sum(p["similarity"] for p in suspicious_pairs) / len(suspicious_pairs)
            # Score: more matches & higher similarity → higher score
            match_ratio = min(1.0, len(suspicious_pairs) / 10.0)
            detection_score = round(avg_sim * 100.0 * match_ratio, 2)
            detection_score = min(100.0, detection_score)
        else:
            detection_score = 0.0

        if detection_score > 60:
            verdict = "CRITICAL: Strong copy-move forgery indicators"
        elif detection_score > 30:
            verdict = "WARNING: Possible copy-move regions detected"
        elif detection_score > 10:
            verdict = "CAUTION: Minor duplicate blocks found — could be natural patterns"
        else:
            verdict = "NORMAL: No significant copy-move patterns"

        return {
            "success": True,
            "suspicious_pairs": suspicious_pairs,
            "detection_score": detection_score,
            "verdict": verdict,
            "blocks_analyzed": n_blocks,
            "pairs_found": len(suspicious_pairs),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────
#  COMPREHENSIVE FORENSIC SCAN (Orchestrator)
# ─────────────────────────────────────────────────────────────────
def comprehensive_forensic_scan(file_path: str) -> dict:
    """
    Orchestrates all forensic analysis methods on a single file.

    Runs:
        - Multi-quality ELA (weight: 50%)
        - EXIF metadata analysis (weight: 30%)
        - Copy-move detection (weight: 20%)

    Args:
        file_path: Path to the image file.

    Returns:
        dict with unified risk score, per-method results, verdict, and ELA heatmap base64.
    """
    result = {
        "success": True,
        "file_path": file_path,
        "unified_risk_score": 0.0,
        "verdict": "",
        "ela_result": None,
        "exif_result": None,
        "copy_move_result": None,
        "ela_base64": "",
        "weight_breakdown": {"ela": 0.50, "exif": 0.30, "copy_move": 0.20},
    }

    # Check if file exists and is an image
    if not os.path.isfile(file_path):
        return {"success": False, "error": f"File not found: {file_path}"}

    # Determine if it's an image
    try:
        img_test = Image.open(file_path)
        img_test.verify()
        is_image = True
    except Exception:
        is_image = False

    if not is_image:
        return {
            "success": False,
            "error": "File is not a recognized image format. Forensic scan requires an image.",
        }

    scores = {}

    # ── 1. Multi-Quality ELA ────────────────────────────────────
    try:
        ela_res = multi_quality_ela(file_path)
        result["ela_result"] = ela_res
        if ela_res.get("success"):
            scores["ela"] = ela_res["composite_score"]
            result["ela_base64"] = ela_res.get("ela_base64", "")
        else:
            scores["ela"] = 0.0
    except Exception as e:
        scores["ela"] = 0.0
        result["ela_result"] = {"success": False, "error": str(e)}

    # ── 2. EXIF Metadata Analysis ───────────────────────────────
    try:
        exif_res = analyze_exif_metadata(file_path)
        result["exif_result"] = exif_res
        if exif_res.get("success"):
            scores["exif"] = exif_res.get("metadata_risk_score", 0.0)
        else:
            scores["exif"] = 0.0
    except Exception as e:
        scores["exif"] = 0.0
        result["exif_result"] = {"success": False, "error": str(e)}

    # ── 3. Copy-Move Detection ──────────────────────────────────
    try:
        cm_res = detect_copy_move(file_path)
        result["copy_move_result"] = cm_res
        if cm_res.get("success"):
            scores["copy_move"] = cm_res.get("detection_score", 0.0)
        else:
            scores["copy_move"] = 0.0
    except Exception as e:
        scores["copy_move"] = 0.0
        result["copy_move_result"] = {"success": False, "error": str(e)}

    # ── Compute unified risk score ──────────────────────────────
    weights = result["weight_breakdown"]
    unified = (
        scores.get("ela", 0) * weights["ela"]
        + scores.get("exif", 0) * weights["exif"]
        + scores.get("copy_move", 0) * weights["copy_move"]
    )
    result["unified_risk_score"] = round(min(100.0, unified), 2)

    # ── Overall verdict ─────────────────────────────────────────
    u = result["unified_risk_score"]
    if u > 70:
        result["verdict"] = "CRITICAL: Multiple forensic indicators suggest document manipulation"
    elif u > 45:
        result["verdict"] = "WARNING: Forensic anomalies detected — manual review recommended"
    elif u > 20:
        result["verdict"] = "CAUTION: Minor forensic flags — low risk of tampering"
    else:
        result["verdict"] = "CLEAN: No significant forensic anomalies detected"

    result["score_breakdown"] = {
        "ela_score": round(scores.get("ela", 0), 2),
        "exif_score": round(scores.get("exif", 0), 2),
        "copy_move_score": round(scores.get("copy_move", 0), 2),
    }

    return result
