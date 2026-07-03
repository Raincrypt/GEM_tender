"""
GEM ANOMALY DETECTION ENGINE v4.0 (Enterprise Optimized)
- Multi-dimensional Isolation Forest
- EWMA Time-Series (timestamp-sorted)
- Network Graph Scoring (degree centrality)
- DBSCAN bid clustering for cartel detection
- Bid timing analysis with burst & entropy-based coordination detection
- Multi-feature extraction with median imputation
"""
import math, statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

# Optional ML imports with graceful fallback
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import DBSCAN
    import numpy as np
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    try:
        import numpy as np
        HAS_NUMPY = True
    except ImportError:
        HAS_NUMPY = False


# ─────────────────────────────────────────────────────────────────
#  MULTI-FEATURE EXTRACTION
# ─────────────────────────────────────────────────────────────────
def extract_multi_features(bids_data: List[dict]) -> dict:
    """
    Build a multi-dimensional feature matrix from bid data.

    Columns:
        - total_amount: Bid monetary value
        - delivery_period: Proposed delivery days
        - vendor_bid_count: Number of bids by this vendor across all tenders
        - vendor_win_rate: Fraction of bids won by this vendor
        - price_to_estimate_ratio: Bid amount / tender estimated value
        - bid_timing_hours: Hours between tender publish and bid submission

    Missing values are imputed with the column median.

    Args:
        bids_data: List of bid dicts with keys like total_amount, delivery_period,
                   vendor_id, vendor_name, status, submitted_at, tender_published_at,
                   estimated_value, etc.

    Returns:
        dict with:
            - feature_matrix (list of lists): NxM feature values
            - feature_names (list[str]): column names
            - bid_indices (list[int]): indices into original bids_data for valid rows
            - imputation_report (dict): per-column count of imputed values
    """
    feature_names = [
        "total_amount", "delivery_period", "vendor_bid_count",
        "vendor_win_rate", "price_to_estimate_ratio", "bid_timing_hours",
    ]

    # Pre-compute vendor-level aggregates
    vendor_bid_counts: Dict[Any, int] = Counter()
    vendor_win_counts: Dict[Any, int] = Counter()
    for b in bids_data:
        vid = b.get("vendor_id") or b.get("vendor_name", "unknown")
        vendor_bid_counts[vid] += 1
        if b.get("status") == "Awarded":
            vendor_win_counts[vid] += 1

    # Extract raw feature rows
    raw_rows = []
    bid_indices = []
    for idx, b in enumerate(bids_data):
        vid = b.get("vendor_id") or b.get("vendor_name", "unknown")
        total_amount = b.get("total_amount")
        delivery_period = b.get("delivery_period")

        # vendor bid count and win rate
        v_bid_count = vendor_bid_counts.get(vid, 0)
        v_win_count = vendor_win_counts.get(vid, 0)
        v_win_rate = v_win_count / max(v_bid_count, 1) if v_bid_count else None

        # price to estimate ratio
        est_val = b.get("estimated_value") or (
            b.get("tender", {}).get("estimated_value") if isinstance(b.get("tender"), dict) else None
        )
        if total_amount and est_val and est_val > 0:
            price_ratio = total_amount / est_val
        else:
            price_ratio = None

        # bid timing hours
        bid_timing = None
        submitted_at = b.get("submitted_at")
        published_at = b.get("tender_published_at") or (
            b.get("tender", {}).get("published_at") if isinstance(b.get("tender"), dict) else None
        )
        if submitted_at and published_at:
            try:
                t_sub = _parse_datetime(submitted_at)
                t_pub = _parse_datetime(published_at)
                if t_sub and t_pub:
                    diff = (t_sub - t_pub).total_seconds()
                    bid_timing = max(0.0, diff / 3600.0)  # hours
            except Exception:
                pass

        row = [
            total_amount if total_amount and total_amount > 0 else None,
            delivery_period if delivery_period and delivery_period > 0 else None,
            float(v_bid_count) if v_bid_count else None,
            v_win_rate,
            price_ratio,
            bid_timing,
        ]
        raw_rows.append(row)
        bid_indices.append(idx)

    if not raw_rows:
        return {
            "feature_matrix": [],
            "feature_names": feature_names,
            "bid_indices": [],
            "imputation_report": {},
        }

    # Median imputation per column
    n_cols = len(feature_names)
    imputation_report = {}
    medians = []
    for col in range(n_cols):
        col_values = [row[col] for row in raw_rows if row[col] is not None]
        if col_values:
            col_values_sorted = sorted(col_values)
            mid = len(col_values_sorted) // 2
            if len(col_values_sorted) % 2 == 0 and len(col_values_sorted) > 1:
                med = (col_values_sorted[mid - 1] + col_values_sorted[mid]) / 2
            else:
                med = col_values_sorted[mid]
        else:
            med = 0.0
        medians.append(med)

    # Fill missing values
    imputed_matrix = []
    for row in raw_rows:
        new_row = []
        for col in range(n_cols):
            if row[col] is None:
                new_row.append(medians[col])
                imputation_report[feature_names[col]] = imputation_report.get(feature_names[col], 0) + 1
            else:
                new_row.append(float(row[col]))
        imputed_matrix.append(new_row)

    return {
        "feature_matrix": imputed_matrix,
        "feature_names": feature_names,
        "bid_indices": bid_indices,
        "imputation_report": imputation_report,
    }


def _parse_datetime(dt_val) -> Optional[datetime]:
    """Parse a datetime from string or return as-is if already datetime."""
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, str):
        for fmt in [
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(dt_val.replace("Z", "+00:00").split("+")[0].strip(), fmt.split("%z")[0])
            except ValueError:
                continue
    return None


# ─────────────────────────────────────────────────────────────────
#  ISOLATION FOREST (single-feature fallback)
# ─────────────────────────────────────────────────────────────────
def isolation_forest_score(target: float, mean_v: float, std_v: float, data_len: int) -> dict:
    """Simplified Isolation Forest anomaly scoring (O(1) execution)."""
    if data_len < 3:
        return {"score": 0.5, "anomaly": False, "label": "INSUFFICIENT_DATA"}

    if std_v == 0: std_v = 1
    z = abs(target - mean_v) / std_v

    # Map z-score to anomaly score (0=normal, 1=anomaly)
    score = min(1.0, z / 3.0)
    return {
        "score": round(score, 4),
        "z_score": round(z, 3),
        "anomaly": score > 0.6,
        "label": "CRITICAL_ANOMALY" if score > 0.8 else "ANOMALY" if score > 0.6 else "BORDERLINE" if score > 0.4 else "NORMAL"
    }


# ─────────────────────────────────────────────────────────────────
#  EWMA TIME-SERIES DETECTOR (now timestamp-sorted)
# ─────────────────────────────────────────────────────────────────
def ewma_detector(series: List[float], span: int = 5,
                  timestamps: Optional[List] = None) -> dict:
    """
    Exponentially Weighted Moving Average anomaly detection.
    If timestamps are provided, series is sorted by timestamp before analysis.
    """
    if timestamps:
        # Sort by timestamp
        paired = list(zip(timestamps, series))
        paired.sort(key=lambda x: _parse_datetime(x[0]) or datetime.min)
        series = [p[1] for p in paired]

    if len(series) < 3:
        return {"alerts": [], "ewma_values": series}

    alpha = 2.0 / (span + 1)
    ewma = [series[0]]

    for i in range(1, len(series)):
        ewma.append(alpha * series[i] + (1 - alpha) * ewma[-1])

    residuals = [abs(series[i] - ewma[i]) for i in range(len(series))]
    res_mean = statistics.mean(residuals)
    res_std = statistics.stdev(residuals) if len(residuals) > 1 else 0
    threshold = res_mean + 2 * res_std

    alerts = []
    for i, r in enumerate(residuals):
        if r > threshold and threshold > 0:
            alerts.append({
                "index": i, "value": series[i], "ewma": round(ewma[i], 2),
                "residual": round(r, 2), "severity": "HIGH" if r > threshold * 1.5 else "MODERATE"
            })

    return {"alerts": alerts, "ewma_values": [round(e, 2) for e in ewma], "threshold": round(threshold, 2)}


# ─────────────────────────────────────────────────────────────────
#  NETWORK ANOMALY SCORING
# ─────────────────────────────────────────────────────────────────
def network_anomaly_score(co_bid_matrix: Dict, vendor_id: int) -> dict:
    """Graph-based anomaly scoring using degree centrality."""
    connections = 0
    total_weight = 0
    unique_nodes = set()

    for (v1, v2), freq in co_bid_matrix.items():
        unique_nodes.add(v1)
        unique_nodes.add(v2)
        if v1 == vendor_id or v2 == vendor_id:
            connections += 1
            total_weight += freq

    n = len(unique_nodes)
    centrality = connections / max(n - 1, 1)
    avg_weight = total_weight / max(connections, 1)
    risk = "HIGH" if centrality > 0.7 and avg_weight > 2 else "MODERATE" if centrality > 0.4 else "LOW"

    return {
        "centrality": round(centrality, 3),
        "connections": connections,
        "avg_co_bid_freq": round(avg_weight, 2),
        "network_risk": risk
    }


# ─────────────────────────────────────────────────────────────────
#  BID TIMING ANALYSIS
# ─────────────────────────────────────────────────────────────────
def analyze_bid_timing(bids_data: List[dict]) -> dict:
    """
    Analyze bid submission timestamps for suspicious patterns.

    Computes:
        - Inter-arrival times between consecutive bids
        - Burst detection: multiple bids within minutes
        - Coordination score using Shannon entropy of time distribution

    Args:
        bids_data: List of bid dicts with 'submitted_at' timestamp fields.

    Returns:
        dict with timing analysis including bursts, entropy, coordination score.
    """
    # Parse and sort timestamps
    timed_bids = []
    for b in bids_data:
        ts = b.get("submitted_at")
        parsed = _parse_datetime(ts) if ts else None
        if parsed:
            timed_bids.append({
                "bid_id": b.get("bid_id"),
                "vendor_id": b.get("vendor_id"),
                "vendor_name": b.get("vendor_name", "?"),
                "timestamp": parsed,
            })

    if len(timed_bids) < 2:
        return {
            "sufficient_data": False,
            "inter_arrival_times": [],
            "bursts": [],
            "coordination_score": 0.0,
            "entropy": 0.0,
            "timing_risk": "INSUFFICIENT_DATA",
        }

    timed_bids.sort(key=lambda x: x["timestamp"])

    # Compute inter-arrival times (seconds)
    inter_arrivals = []
    for i in range(1, len(timed_bids)):
        diff_sec = (timed_bids[i]["timestamp"] - timed_bids[i - 1]["timestamp"]).total_seconds()
        inter_arrivals.append({
            "between": [timed_bids[i - 1].get("vendor_name", "?"), timed_bids[i].get("vendor_name", "?")],
            "bid_ids": [timed_bids[i - 1].get("bid_id"), timed_bids[i].get("bid_id")],
            "seconds": round(diff_sec, 1),
            "minutes": round(diff_sec / 60, 2),
        })

    # Detect bursts: groups of bids within 5 minutes of each other
    burst_threshold_sec = 300  # 5 minutes
    bursts = []
    current_burst = [timed_bids[0]]
    for i in range(1, len(timed_bids)):
        diff = (timed_bids[i]["timestamp"] - current_burst[-1]["timestamp"]).total_seconds()
        if diff <= burst_threshold_sec:
            current_burst.append(timed_bids[i])
        else:
            if len(current_burst) >= 2:
                burst_span = (current_burst[-1]["timestamp"] - current_burst[0]["timestamp"]).total_seconds()
                bursts.append({
                    "count": len(current_burst),
                    "vendors": [b.get("vendor_name", "?") for b in current_burst],
                    "vendor_ids": [b.get("vendor_id") for b in current_burst],
                    "bid_ids": [b.get("bid_id") for b in current_burst],
                    "span_seconds": round(burst_span, 1),
                    "start_time": str(current_burst[0]["timestamp"]),
                })
            current_burst = [timed_bids[i]]
    # Final burst
    if len(current_burst) >= 2:
        burst_span = (current_burst[-1]["timestamp"] - current_burst[0]["timestamp"]).total_seconds()
        bursts.append({
            "count": len(current_burst),
            "vendors": [b.get("vendor_name", "?") for b in current_burst],
            "vendor_ids": [b.get("vendor_id") for b in current_burst],
            "bid_ids": [b.get("bid_id") for b in current_burst],
            "span_seconds": round(burst_span, 1),
            "start_time": str(current_burst[0]["timestamp"]),
        })

    # Coordination score via Shannon entropy of hourly bins
    # Low entropy = bids clustered in few time slots = suspicious
    hour_bins = Counter()
    for tb in timed_bids:
        hour_key = tb["timestamp"].strftime("%Y-%m-%d_%H")
        hour_bins[hour_key] += 1

    total_bids = sum(hour_bins.values())
    entropy = 0.0
    for count in hour_bins.values():
        p = count / total_bids
        if p > 0:
            entropy -= p * math.log2(p)

    # Max entropy = all bids in different slots = log2(n)
    max_entropy = math.log2(max(len(hour_bins), 1)) if len(hour_bins) > 1 else 1.0
    normalized_entropy = entropy / max(max_entropy, 1e-9)

    # Coordination score: inverse of normalized entropy
    # Low entropy (clustered submissions) → high coordination score
    coordination_score = round(max(0.0, 1.0 - normalized_entropy) * 100.0, 2)

    # Overall timing risk assessment
    if coordination_score > 70 or len(bursts) >= 3:
        timing_risk = "CRITICAL"
    elif coordination_score > 45 or len(bursts) >= 2:
        timing_risk = "HIGH"
    elif coordination_score > 25 or len(bursts) >= 1:
        timing_risk = "MODERATE"
    else:
        timing_risk = "LOW"

    return {
        "sufficient_data": True,
        "total_timed_bids": len(timed_bids),
        "inter_arrival_times": inter_arrivals[:30],  # Cap output
        "bursts": bursts,
        "entropy": round(entropy, 4),
        "normalized_entropy": round(normalized_entropy, 4),
        "coordination_score": coordination_score,
        "timing_risk": timing_risk,
    }


# ─────────────────────────────────────────────────────────────────
#  BID CLUSTER DETECTION (DBSCAN)
# ─────────────────────────────────────────────────────────────────
def detect_bid_clusters(bids_data: List[dict]) -> dict:
    """
    Detect cartel-like groups using DBSCAN clustering on bid amounts
    combined with vendor co-occurrence patterns.

    Features:
        - Normalized bid amount (per tender)
        - Vendor co-occurrence frequency

    Args:
        bids_data: List of bid dicts with tender_id, vendor_id, vendor_name, total_amount.

    Returns:
        dict with cluster groups, vendor names, bid IDs, and suspicion scores.
    """
    if len(bids_data) < 4:
        return {
            "sufficient_data": False,
            "clusters": [],
            "suspicion_summary": "Not enough bids for cluster analysis",
        }

    # Group bids by tender
    tender_bids: Dict[Any, List[dict]] = defaultdict(list)
    for b in bids_data:
        tid = b.get("tender_id")
        if tid:
            tender_bids[tid].append(b)

    # Build vendor co-occurrence matrix
    vendor_pairs: Dict[tuple, int] = Counter()
    all_vendor_ids = set()
    for tid, bids in tender_bids.items():
        vids = list(set(b.get("vendor_id") or b.get("vendor_name", "?") for b in bids))
        all_vendor_ids.update(vids)
        for i in range(len(vids)):
            for j in range(i + 1, len(vids)):
                pair = tuple(sorted([vids[i], vids[j]]))
                vendor_pairs[pair] += 1

    if not HAS_SKLEARN:
        # Fallback: simple frequency-based grouping
        # Identify vendors that frequently co-bid
        suspicious_groups = []
        seen = set()
        for (v1, v2), freq in vendor_pairs.most_common():
            if freq >= 2 and v1 not in seen and v2 not in seen:
                group_bids = [
                    b for b in bids_data
                    if (b.get("vendor_id") or b.get("vendor_name")) in (v1, v2)
                ]
                group_amounts = [b.get("total_amount", 0) for b in group_bids if b.get("total_amount")]
                if group_amounts:
                    amount_std = statistics.stdev(group_amounts) if len(group_amounts) > 1 else 0
                    amount_mean = statistics.mean(group_amounts)
                    # Low variance in amounts among co-bidders = suspicious
                    cv = amount_std / max(amount_mean, 1)
                    suspicion = round(max(0, min(100, (1 - cv) * freq * 20)), 2)
                else:
                    suspicion = round(freq * 15.0, 2)

                suspicious_groups.append({
                    "cluster_id": len(suspicious_groups),
                    "vendors": [str(v1), str(v2)],
                    "co_bid_frequency": freq,
                    "bid_count": len(group_bids),
                    "bid_ids": [b.get("bid_id") for b in group_bids if b.get("bid_id")],
                    "suspicion_score": min(100, suspicion),
                })
                seen.add(v1)
                seen.add(v2)

        return {
            "sufficient_data": True,
            "method": "frequency_grouping_fallback",
            "clusters": suspicious_groups[:20],
            "suspicion_summary": (
                f"Found {len(suspicious_groups)} suspicious vendor group(s) via co-bid frequency"
                if suspicious_groups else "No suspicious clusters detected"
            ),
        }

    # ── DBSCAN approach with scikit-learn ──────────────────────
    # Build per-bid feature vector: [normalized_amount, co_occurrence_score]
    bid_features = []
    bid_meta = []
    for b in bids_data:
        tid = b.get("tender_id")
        vid = b.get("vendor_id") or b.get("vendor_name", "?")
        amount = b.get("total_amount", 0) or 0

        # Normalize amount within its tender group
        tender_group = tender_bids.get(tid, [])
        group_amounts = [gb.get("total_amount", 0) for gb in tender_group if gb.get("total_amount")]
        if group_amounts and len(group_amounts) > 1:
            g_mean = statistics.mean(group_amounts)
            g_std = statistics.stdev(group_amounts)
            norm_amount = (amount - g_mean) / max(g_std, 1)
        elif group_amounts:
            norm_amount = 0.0
        else:
            norm_amount = 0.0

        # Co-occurrence score for this vendor
        co_occ_total = sum(freq for (v1, v2), freq in vendor_pairs.items() if vid in (v1, v2))

        bid_features.append([norm_amount, float(co_occ_total)])
        bid_meta.append({
            "bid_id": b.get("bid_id"),
            "vendor_id": vid,
            "vendor_name": b.get("vendor_name", "?"),
            "amount": amount,
            "tender_id": tid,
        })

    X = np.array(bid_features)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # DBSCAN clustering
    # eps tuned for normalized features; min_samples=2 to catch pairs
    db = DBSCAN(eps=0.8, min_samples=2)
    labels = db.fit_predict(X_scaled)

    # Group results by cluster label
    cluster_groups: Dict[int, list] = defaultdict(list)
    for i, label in enumerate(labels):
        if label != -1:  # -1 = noise
            cluster_groups[label].append(bid_meta[i])

    clusters = []
    for cluster_id, members in cluster_groups.items():
        vendors_in_cluster = list(set(m["vendor_name"] for m in members))
        vendor_ids = list(set(m["vendor_id"] for m in members))
        amounts = [m["amount"] for m in members if m["amount"]]

        # Suspicion score based on cluster tightness and co-occurrence
        if amounts and len(amounts) > 1:
            cv = statistics.stdev(amounts) / max(statistics.mean(amounts), 1)
            co_occ_sum = sum(
                vendor_pairs.get(tuple(sorted([v1, v2])), 0)
                for i, v1 in enumerate(vendor_ids)
                for v2 in vendor_ids[i + 1:]
            )
            # Lower CV + higher co-occurrence = higher suspicion
            suspicion = round(max(0, min(100, (1 - min(cv, 1)) * 50 + co_occ_sum * 10)), 2)
        else:
            suspicion = 20.0

        clusters.append({
            "cluster_id": int(cluster_id),
            "vendors": vendors_in_cluster,
            "vendor_ids": [str(v) for v in vendor_ids],
            "bid_count": len(members),
            "bid_ids": [m["bid_id"] for m in members if m.get("bid_id")],
            "suspicion_score": suspicion,
        })

    clusters.sort(key=lambda c: c["suspicion_score"], reverse=True)

    return {
        "sufficient_data": True,
        "method": "DBSCAN",
        "clusters": clusters[:20],
        "noise_bids": int(sum(1 for l in labels if l == -1)),
        "suspicion_summary": (
            f"DBSCAN found {len(clusters)} cluster(s) with {sum(c['bid_count'] for c in clusters)} bids"
            if clusters else "No suspicious clusters detected"
        ),
    }


# ─────────────────────────────────────────────────────────────────
#  FORENSIC ANOMALY ASSESSMENTS (Benford, CV, Entropy)
# ─────────────────────────────────────────────────────────────────

def compute_benford_analysis(amounts: List[float]) -> dict:
    """
    Performs Benford's Law first-digit and second-digit compliance analysis.
    Deviation suggests non-random, artificial price generation.
    """
    import math
    valid_amounts = [a for a in amounts if a and a > 0]
    n = len(valid_amounts)
    if n < 10:
        return {"first_digit_deviation": 0.0, "second_digit_deviation": 0.0, "status": "INSUFFICIENT_DATA", "risk": "LOW"}
        
    first_digits = []
    second_digits = []
    
    for a in valid_amounts:
        s = str(a).replace(".", "").lstrip("0")
        if len(s) >= 1:
            first_digits.append(int(s[0]))
        if len(s) >= 2:
            second_digits.append(int(s[1]))
            
    first_theory = {d: math.log10(1 + 1.0 / d) for d in range(1, 10)}
    
    second_theory = {}
    for d in range(10):
        sum_p = 0.0
        for k in range(1, 10):
            sum_p += math.log10(1 + 1.0 / (10 * k + d))
        second_theory[d] = sum_p

    first_counts = Counter(first_digits)
    second_counts = Counter(second_digits)
    
    mad_first = sum(abs((first_counts[d] / n) - first_theory[d]) for d in range(1, 10)) / 9.0
    
    n_second = len(second_digits)
    mad_second = sum(abs((second_counts[d] / n_second) - second_theory[d]) for d in range(10)) / 10.0 if n_second > 0 else 0.0

    risk = "LOW"
    if mad_first > 0.12 or mad_second > 0.08:
        risk = "CRITICAL — Severe Digit Anomaly"
    elif mad_first > 0.06 or mad_second > 0.04:
        risk = "HIGH — Digit Anomaly Detected"
    elif mad_first > 0.03 or mad_second > 0.02:
        risk = "MODERATE"
        
    return {
        "n_samples": n,
        "first_digit_mad": round(mad_first, 4),
        "second_digit_mad": round(mad_second, 4),
        "first_digit_distribution": {d: round(first_counts[d] / n, 3) for d in range(1, 10)},
        "second_digit_distribution": {d: round(second_counts[d] / n_second, 3) for d in range(10)} if n_second > 0 else {},
        "risk": risk
    }


def compute_cross_tender_cv(bids_data: List[dict]) -> dict:
    """
    Computes cross-tender Coefficient of Variation (CV) for each vendor.
    Low CV (< 0.05) across different tenders indicates suspiciously rigid pricing.
    """
    vendor_bids = defaultdict(list)
    for b in bids_data:
        vid = b.get("vendor_id") or b.get("vendor_name", "unknown")
        amount = b.get("total_amount")
        if vid and amount and amount > 0:
            vendor_bids[vid].append(amount)
            
    cv_results = {}
    for vid, amounts in vendor_bids.items():
        if len(amounts) < 3:
            continue
        mean_val = statistics.mean(amounts)
        std_val = statistics.stdev(amounts) if len(amounts) > 1 else 0.0
        cv = std_val / mean_val if mean_val > 0 else 0.0
        
        risk = "LOW"
        if cv < 0.02:
            risk = "CRITICAL — Extremely Rigid Pricing"
        elif cv < 0.05:
            risk = "HIGH — Suspiciously Low Pricing Variance"
        elif cv < 0.10:
            risk = "MODERATE"
            
        cv_results[str(vid)] = {
            "n_bids": len(amounts),
            "mean": round(mean_val, 2),
            "std": round(std_val, 2),
            "cv": round(cv, 4),
            "risk": risk
        }
    return cv_results


def compute_all_tenders_entropy(bids_data: List[dict]) -> dict:
    """
    Computes Shannon price entropy for each tender.
    Low normalized entropy (< 0.3) indicates severe pricing clustering.
    """
    import math
    tender_bids = defaultdict(list)
    for b in bids_data:
        tid = b.get("tender_id")
        amount = b.get("total_amount")
        if tid and amount and amount > 0:
            tender_bids[tid].append(amount)
            
    entropy_results = {}
    for tid, amounts in tender_bids.items():
        n = len(amounts)
        if n < 2:
            continue
        min_v, max_v = min(amounts), max(amounts)
        if min_v == max_v:
            entropy_results[str(tid)] = {
                "entropy": 0.0,
                "normalized_entropy": 0.0,
                "risk": "CRITICAL — Identical Bids Detected"
            }
            continue
            
        n_bins = 5
        bin_width = (max_v - min_v) / n_bins
        bins = [0] * n_bins
        for v in amounts:
            idx = min(int((v - min_v) / bin_width), n_bins - 1)
            bins[idx] += 1
            
        entropy = 0.0
        for count in bins:
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
                
        max_entropy = math.log2(n_bins)
        normalized = entropy / max_entropy if max_entropy > 0 else 0.0
        
        risk = "LOW"
        if normalized < 0.25:
            risk = "CRITICAL — Severe Pricing Clustering"
        elif normalized < 0.50:
            risk = "HIGH — Price Clustering Detected"
        elif normalized < 0.75:
            risk = "MODERATE"
            
        entropy_results[str(tid)] = {
            "entropy": round(entropy, 4),
            "normalized_entropy": round(normalized, 4),
            "risk": risk,
            "n_bids": n
        }
    return entropy_results


# ─────────────────────────────────────────────────────────────────
#  COMPREHENSIVE ANOMALY SCAN
# ─────────────────────────────────────────────────────────────────
def comprehensive_anomaly_scan(bids_data: List[dict], vendors_data: List[dict]) -> dict:
    """
    Full system anomaly scan combining all detection methods.

    Pipeline:
        1. Multi-feature extraction with median imputation
        2. Multi-dimensional Isolation Forest (all features)
        3. EWMA on time-ordered bid amounts
        4. Network anomaly scoring (co-bid graph)
        5. Bid timing analysis (burst & coordination detection)
        6. Forensic tests (Benford, Price Entropy, Cross-Tender CV, Tukey/Grubbs)

    Returns enriched results with per-feature anomaly contributions.
    """
    import ai_risk_engine as are

    results = {
        "isolation_forest": [],
        "ewma": {},
        "network": [],
        "bid_timing": {},
        "benford": {},
        "price_entropy": {},
        "cross_tender_cv": {},
        "summary": {},
    }

    # ── Extract multi-dimensional features ──────────────────────
    feature_data = extract_multi_features(bids_data)
    feature_matrix = feature_data["feature_matrix"]
    feature_names = feature_data["feature_names"]
    bid_indices = feature_data["bid_indices"]

    amounts = [b["total_amount"] for b in bids_data if b.get("total_amount") and b["total_amount"] > 0]
    mean_amt = statistics.mean(amounts) if amounts else 0
    std_amt = statistics.stdev(amounts) if len(amounts) > 1 else 1

    # ── Multi-dimensional Isolation Forest ──────────────────────
    try:
        if not HAS_SKLEARN:
            raise ImportError("scikit-learn not available")
        if len(feature_matrix) < 5:
            raise ValueError("Not enough data for multi-dim Isolation Forest")

        X = np.array(feature_matrix)
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        clf = IsolationForest(contamination=0.1, random_state=42)
        preds = clf.fit_predict(X_scaled)
        scores = clf.decision_function(X_scaled)

        for idx_pos, bid_idx in enumerate(bid_indices):
            b = bids_data[bid_idx]
            is_anomaly = bool(preds[idx_pos] == -1)
            raw_score = float(-scores[idx_pos])
            norm_score = round((raw_score + 1) / 2, 4)  # Normalize roughly 0 to 1

            # Per-feature anomaly contribution (z-scores of the scaled features)
            feature_contributions = {}
            for f_idx, f_name in enumerate(feature_names):
                z_val = abs(float(X_scaled[idx_pos, f_idx]))
                feature_contributions[f_name] = round(z_val, 3)

            iso = {
                "score": norm_score,
                "z_score": round(abs(b.get("total_amount", 0) - mean_amt) / max(std_amt, 1), 3),
                "anomaly": is_anomaly,
                "label": (
                    "CRITICAL_ANOMALY" if is_anomaly and raw_score > 0.1
                    else "ANOMALY" if is_anomaly
                    else "NORMAL"
                ),
                "bid_id": b.get("bid_id"),
                "vendor_name": b.get("vendor_name", "?"),
                "amount": b.get("total_amount", 0),
                "tender_id": b.get("tender_id"),
                "feature_contributions": feature_contributions,
            }
            results["isolation_forest"].append(iso)

    except Exception:
        # Fallback: single-feature z-score based scoring
        amounts_len = len(amounts)
        for b in bids_data:
            if b.get("total_amount") and b["total_amount"] > 0:
                iso = isolation_forest_score(b["total_amount"], mean_amt, std_amt, amounts_len)
                iso["bid_id"] = b.get("bid_id")
                iso["vendor_name"] = b.get("vendor_name", "?")
                iso["amount"] = b["total_amount"]
                iso["tender_id"] = b.get("tender_id")
                iso["feature_contributions"] = {"total_amount": iso.get("z_score", 0)}
                results["isolation_forest"].append(iso)

    # ── EWMA on bid amounts (sorted by submitted_at) ────────────
    if amounts:
        timestamps = []
        sorted_amounts = []
        for b in bids_data:
            if b.get("total_amount") and b["total_amount"] > 0:
                timestamps.append(b.get("submitted_at"))
                sorted_amounts.append(b["total_amount"])

        results["ewma"] = ewma_detector(sorted_amounts, timestamps=timestamps)

    # ── Network anomaly scoring ─────────────────────────────────
    tender_vendors = defaultdict(list)
    for b in bids_data:
        tid = b.get("tender_id")
        vid = b.get("vendor_id")
        if tid and vid:
            tender_vendors[tid].append(vid)

    co_bid_matrix = Counter()
    for tid, vids in tender_vendors.items():
        unique_vids = list(set(vids))
        for i in range(len(unique_vids)):
            for j in range(i + 1, len(unique_vids)):
                pair = (min(unique_vids[i], unique_vids[j]), max(unique_vids[i], unique_vids[j]))
                co_bid_matrix[pair] += 1

    all_vendor_ids = set()
    for b in bids_data:
        vid = b.get("vendor_id")
        if vid:
            all_vendor_ids.add(vid)

    for vid in all_vendor_ids:
        net_score = network_anomaly_score(co_bid_matrix, vid)
        v_name = "?"
        for b in bids_data:
            if b.get("vendor_id") == vid:
                v_name = b.get("vendor_name", "?")
                break
        net_score["vendor_id"] = vid
        net_score["vendor_name"] = v_name
        results["network"].append(net_score)

    # ── Bid timing analysis ─────────────────────────────────────
    results["bid_timing"] = analyze_bid_timing(bids_data)

    # ── Forensic checks: Benford, Entropy, Cross-Tender CV ──────
    benford_res = compute_benford_analysis(amounts)
    cv_res = compute_cross_tender_cv(bids_data)
    entropy_res = compute_all_tenders_entropy(bids_data)
    
    results["benford"] = benford_res
    results["cross_tender_cv"] = cv_res
    results["price_entropy"] = entropy_res

    # Group bids by tender to do per-tender Tukey/Grubbs
    tender_amounts = defaultdict(list)
    for b in bids_data:
        tid = b.get("tender_id")
        amt = b.get("total_amount")
        if tid and amt and amt > 0:
            tender_amounts[tid].append(amt)
            
    tender_stats = {}
    for tid, amts in tender_amounts.items():
        if len(amts) >= 3:
            tender_stats[tid] = {
                "tukey": are.compute_tukey_fences(amts),
                "grubbs": are.compute_grubbs_test(amts)
            }

    # Enrich isolation forest records with Tukey / Grubbs outlier status
    for iso in results["isolation_forest"]:
        tid = iso.get("tender_id")
        amt = iso["amount"]
        if tid in tender_stats:
            t_stat = tender_stats[tid]
            if amt in t_stat["tukey"].get("extreme_outliers", []):
                iso["tukey_status"] = "EXTREME_OUTLIER"
            elif amt in t_stat["tukey"].get("mild_outliers", []):
                iso["tukey_status"] = "MILD_OUTLIER"
            else:
                iso["tukey_status"] = "NORMAL"
            iso["grubbs_significant"] = bool(t_stat["grubbs"].get("significant") and amt == t_stat["grubbs"].get("outlier"))
        else:
            iso["tukey_status"] = "NORMAL"
            iso["grubbs_significant"] = False

    # ── Summary ─────────────────────────────────────────────────
    anomalies = [r for r in results["isolation_forest"] if r.get("anomaly")]
    network_high = [n for n in results["network"] if n.get("network_risk") == "HIGH"]
    timing_risk = results.get("bid_timing", {}).get("timing_risk", "LOW")

    # Determine overall risk from all signals
    risk_signals = 0
    if len(anomalies) > 3:
        risk_signals += 3
    elif len(anomalies) > 1:
        risk_signals += 2
    elif len(anomalies) > 0:
        risk_signals += 1
    if network_high:
        risk_signals += 2
    if timing_risk in ("CRITICAL", "HIGH"):
        risk_signals += 2
    elif timing_risk == "MODERATE":
        risk_signals += 1

    if benford_res.get("risk") in ("CRITICAL — Severe Digit Anomaly", "HIGH — Digit Anomaly Detected"):
        risk_signals += 2
    for tid, ent in entropy_res.items():
        if ent.get("risk") in ("CRITICAL — Severe Pricing Clustering", "HIGH — Price Clustering Detected"):
            risk_signals += 1
            break

    if risk_signals >= 5:
        overall_risk = "CRITICAL"
    elif risk_signals >= 3:
        overall_risk = "HIGH"
    elif risk_signals >= 1:
        overall_risk = "MODERATE"
    else:
        overall_risk = "LOW"

    results["summary"] = {
        "total_scanned": len(bids_data),
        "anomalies_found": len(anomalies),
        "critical_count": sum(1 for a in anomalies if a.get("label") == "CRITICAL_ANOMALY"),
        "ewma_alerts": len(results["ewma"].get("alerts", [])),
        "network_high_risk_vendors": len(network_high),
        "timing_risk": timing_risk,
        "timing_bursts": len(results.get("bid_timing", {}).get("bursts", [])),
        "overall_risk": overall_risk,
        "features_used": feature_names,
        "imputation_report": feature_data.get("imputation_report", {}),
    }
    return results


# ─────────────────────────────────────────────────────────────────
#  PREDICTIVE VENDOR RISK MODEL (GradientBoosting / Heuristic)
# ─────────────────────────────────────────────────────────────────

_PRED_FEATURE_NAMES = [
    "bid_count",           # Total number of bids submitted
    "win_rate",            # Fraction of bids won (0-1)
    "avg_price_cv",        # Cross-tender price volatility (coefficient of variation)
    "avg_per_ratio",       # Average price-to-estimate ratio
    "dq_rate",             # Disqualification rate (fraction of bids DQ'd)
    "blacklist_flag",      # 1 if vendor is blacklisted else 0
    "avg_delivery_days",   # Average delivery period across bids
    "multi_tender_rate",   # Fraction of tenders with this vendor present
    "network_centrality",  # Centrality in the co-bidding collusion graph
    "coordination_score",  # Submission timestamp coordinate burstiness & entropy rating
    "benford_deviation",   # Digit-level deviation score from Benford's Law
    "price_deviation_z",   # Average price deviation z-score relative to other bidders
]


def _build_vendor_feature_vector(vendor_id: Any, all_bids: List[dict], n_tenders: int) -> dict:
    """
    Build a feature vector for a single vendor from raw bid records.

    Returns dict of feature_name -> float value.
    """
    my_bids = [b for b in all_bids if b.get("vendor_id") == vendor_id]
    if not my_bids:
        return {k: 0.0 for k in _PRED_FEATURE_NAMES}

    bid_count = float(len(my_bids))
    win_count = sum(1 for b in my_bids if (b.get("status") or "").lower() in ("awarded", "won", "l1"))
    win_rate = win_count / bid_count

    dq_count = sum(1 for b in my_bids if b.get("is_disqualified"))
    dq_rate = dq_count / bid_count

    # Price CV across bids
    amounts = [b.get("total_amount") or 0 for b in my_bids if b.get("total_amount", 0) > 0]
    if len(amounts) > 1:
        mean_a = sum(amounts) / len(amounts)
        std_a = math.sqrt(sum((a - mean_a) ** 2 for a in amounts) / len(amounts))
        avg_price_cv = (std_a / mean_a) if mean_a > 0 else 0.0
    else:
        avg_price_cv = 0.0

    # Average PER (price-to-estimate ratio)
    per_values = []
    for b in my_bids:
        est = b.get("estimated_value") or b.get("tender_estimated_value") or 0
        amt = b.get("total_amount") or 0
        if est > 0 and amt > 0:
            per_values.append(amt / est)
    avg_per_ratio = sum(per_values) / max(len(per_values), 1) if per_values else 1.0

    # Blacklist flag
    blacklist_flag = float(any(b.get("is_blacklisted") for b in my_bids))

    # Average delivery days
    deliveries = [b.get("delivery_period") or 0 for b in my_bids if b.get("delivery_period")]
    avg_delivery_days = sum(deliveries) / max(len(deliveries), 1) if deliveries else 60.0

    # Multi-tender participation rate
    tenders_participated_set = set(b.get("tender_id") for b in my_bids if b.get("tender_id"))
    multi_tender_rate = len(tenders_participated_set) / max(n_tenders, 1)

    # 1. Network Centrality
    tender_vendors = defaultdict(list)
    for b in all_bids:
        tid = b.get("tender_id")
        vid = b.get("vendor_id")
        if tid and vid:
            tender_vendors[tid].append(vid)

    co_bid_matrix = Counter()
    for tid, vids in tender_vendors.items():
        unique_vids = list(set(vids))
        for i in range(len(unique_vids)):
            for j in range(i + 1, len(unique_vids)):
                pair = (min(unique_vids[i], unique_vids[j]), max(unique_vids[i], unique_vids[j]))
                co_bid_matrix[pair] += 1

    net_res = network_anomaly_score(co_bid_matrix, vendor_id)
    network_centrality = float(net_res.get("centrality", 0.0))

    # 2. Timing Coordination Score
    coor_scores = []
    for tid in tenders_participated_set:
        tbids = [b for b in all_bids if b.get("tender_id") == tid]
        timing_res = analyze_bid_timing(tbids)
        if timing_res.get("sufficient_data"):
            coor_scores.append(timing_res.get("coordination_score", 0.0))
    coordination_score = sum(coor_scores) / len(coor_scores) if coor_scores else 0.0
    coordination_score = float(coordination_score / 100.0)

    # 3. Benford Deviation
    if len(amounts) >= 3:
        first_digits = []
        for a in amounts:
            s = str(a).replace(".", "").lstrip("0")
            if s:
                first_digits.append(int(s[0]))
        theory = {d: math.log10(1 + 1.0 / d) for d in range(1, 10)}
        counts = Counter(first_digits)
        benford_deviation = float(sum(abs((counts[d] / len(amounts)) - theory[d]) for d in range(1, 10)) / 9.0)
    else:
        benford_deviation = 0.0

    # 4. Price Deviation Z-Score
    price_devs = []
    for b in my_bids:
        tid = b.get("tender_id")
        amt = b.get("total_amount") or 0
        if tid and amt > 0:
            tbids = [tb.get("total_amount") or 0 for tb in all_bids if tb.get("tender_id") == tid and tb.get("total_amount", 0) > 0]
            if len(tbids) > 1:
                mean_t = sum(tbids) / len(tbids)
                std_t = math.sqrt(sum((x - mean_t) ** 2 for x in tbids) / len(tbids))
                if std_t > 0:
                    price_devs.append((amt - mean_t) / std_t)
                else:
                    price_devs.append(0.0)
    price_deviation_z = float(abs(sum(price_devs) / len(price_devs))) if price_devs else 0.0

    return {
        "bid_count": bid_count,
        "win_rate": win_rate,
        "avg_price_cv": avg_price_cv,
        "avg_per_ratio": avg_per_ratio,
        "dq_rate": dq_rate,
        "blacklist_flag": blacklist_flag,
        "avg_delivery_days": avg_delivery_days,
        "multi_tender_rate": multi_tender_rate,
        "network_centrality": network_centrality,
        "coordination_score": coordination_score,
        "benford_deviation": benford_deviation,
        "price_deviation_z": price_deviation_z,
    }


def _heuristic_risk_score(features: dict) -> float:
    """
    Fallback heuristic risk score (0=safe, 1=risky) when training data insufficient.
    Based on domain knowledge of procurement red flags.
    """
    score = 0.0

    # High disqualification rate is a strong signal
    dq_rate = features.get("dq_rate", 0)
    score += min(dq_rate * 0.35, 0.35)

    # Blacklisted vendors are maximum risk
    if features.get("blacklist_flag", 0) > 0:
        score += 0.40

    # Extreme price volatility signals bid manipulation
    cv = features.get("avg_price_cv", 0)
    if cv > 0.3:
        score += min((cv - 0.3) * 0.5, 0.15)

    # Very low PER (predatory pricing) or very high PER (price padding)
    per = features.get("avg_per_ratio", 1.0)
    if per < 0.7:
        score += 0.10   # Predatory
    elif per > 1.3:
        score += 0.08   # Inflated

    # High win-rate with few bids may indicate bid rigging
    bid_count = features.get("bid_count", 1)
    win_rate = features.get("win_rate", 0)
    if bid_count >= 3 and win_rate > 0.8:
        score += 0.05   # Suspiciously high win rate

    # Network centrality collusion risk
    net_c = features.get("network_centrality", 0.0)
    if net_c > 0.6:
        score += 0.10

    # Timing coordination collusion risk
    coord = features.get("coordination_score", 0.0)
    if coord > 0.6:
        score += 0.10

    return round(min(score, 1.0), 4)


def train_vendor_risk_model(all_bids: List[dict], n_tenders: int = 0) -> dict:
    """
    Train an ensemble VotingClassifier (GradientBoosting + RandomForest + LogisticRegression)
    on vendor bid history using GridSearchCV and StratifiedKFold cross-validation.

    The training label is: vendor_risk = 1 if vendor has any DQ or blacklist, else 0.
    With less than 10 vendors, falls back entirely to heuristic/density scoring.
    """
    vendor_ids = list(set(b.get("vendor_id") for b in all_bids if b.get("vendor_id") is not None))

    if len(vendor_ids) < 10:
        return {
            "model_type": "Heuristic",
            "vendor_ids": vendor_ids,
            "feature_importances": {f: 1.0 / len(_PRED_FEATURE_NAMES) for f in _PRED_FEATURE_NAMES},
            "training_samples": len(vendor_ids),
        }

    # Build feature matrix
    X = []
    y = []
    for vid in vendor_ids:
        fv = _build_vendor_feature_vector(vid, all_bids, n_tenders)
        X.append([fv[f] for f in _PRED_FEATURE_NAMES])
        # Label: risky if blacklisted OR high DQ rate
        label = 1 if fv["blacklist_flag"] > 0 or fv["dq_rate"] > 0.5 else 0
        y.append(label)

    try:
        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier, VotingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GridSearchCV, StratifiedKFold
        from sklearn.preprocessing import StandardScaler

        X_arr = np.array(X)
        y_arr = np.array(y)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X_arr)

        # Base estimators
        gbdt = GradientBoostingClassifier(random_state=42)
        rf = RandomForestClassifier(random_state=42)
        lr = LogisticRegression(max_iter=1000, random_state=42)

        # Create soft-voting ensemble
        ensemble = VotingClassifier(
            estimators=[('gbdt', gbdt), ('rf', rf), ('lr', lr)],
            voting='soft'
        )

        # Grid search parameters for the ensemble
        # Since we use VotingClassifier, prefix param names with the estimator label
        param_grid = {
            'gbdt__n_estimators': [50, 100],
            'gbdt__learning_rate': [0.05, 0.1],
            'gbdt__max_depth': [2, 3],
            'rf__n_estimators': [50, 100],
            'rf__max_depth': [3, 5, None]
        }

        # Use 3-fold CV if class distributions are small, else 5-fold
        n_splits = min(5, max(2, sum(y_arr == 1), sum(y_arr == 0)))
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

        grid = GridSearchCV(
            estimator=ensemble,
            param_grid=param_grid,
            cv=cv,
            scoring='accuracy',
            n_jobs=1
        )

        grid.fit(X_scaled, y_arr)
        best_model = grid.best_estimator_

        # Extract feature importances (VotingClassifier doesn't have feature_importances_ directly,
        # but we can average the importances of gbdt and rf, ignoring lr)
        best_gbdt = best_model.named_estimators_['gbdt']
        best_rf = best_model.named_estimators_['rf']
        avg_importances = (best_gbdt.feature_importances_ + best_rf.feature_importances_) / 2.0
        importances = dict(zip(_PRED_FEATURE_NAMES, avg_importances.tolist()))

        return {
            "model_type": f"EnsembleVoting (Accuracy: {grid.best_score_:.1%})",
            "vendor_ids": vendor_ids,
            "feature_importances": importances,
            "training_samples": len(vendor_ids),
            "_clf": best_model,
            "_scaler": scaler,
        }

    except Exception as e:
        print(f"[anomaly_detector] Failed to train ensemble model: {e}. Falling back to basic GBDT.")
        try:
            import numpy as np
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.preprocessing import StandardScaler

            X_arr = np.array(X)
            y_arr = np.array(y)

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_arr)

            clf = GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=3,
                random_state=42,
            )
            clf.fit(X_scaled, y_arr)

            importances = dict(zip(_PRED_FEATURE_NAMES, clf.feature_importances_.tolist()))

            return {
                "model_type": "GradientBoosting",
                "vendor_ids": vendor_ids,
                "feature_importances": importances,
                "training_samples": len(vendor_ids),
                "_clf": clf,
                "_scaler": scaler,
            }
        except Exception:
            return {
                "model_type": "Heuristic",
                "vendor_ids": vendor_ids,
                "feature_importances": {f: 1.0 / len(_PRED_FEATURE_NAMES) for f in _PRED_FEATURE_NAMES},
                "training_samples": len(vendor_ids),
            }


def predict_vendor_risk(
    all_bids: List[dict],
    all_vendor_ids: List[Any],
    vendor_name_map: Optional[Dict[Any, str]] = None,
    n_tenders: int = 0,
) -> List[dict]:
    """
    Predict default/risk probability for every vendor using trained model or heuristic.

    Args:
        all_bids: All bid records.
        all_vendor_ids: List of vendor IDs to score.
        vendor_name_map: Optional {vendor_id: company_name}.
        n_tenders: Total tender count for multi-tender-rate feature.

    Returns:
        List of vendor risk dicts, sorted by risk_score descending.
        Each dict:
          - vendor_id, company_name
          - risk_score (0-1, higher = riskier)
          - risk_level ("CRITICAL" / "HIGH" / "MODERATE" / "LOW")
          - model_type
          - feature_contributions: dict of feature -> value
          - risk_factors: list of human-readable risk reason strings
    """
    vendor_name_map = vendor_name_map or {}

    # Train model once
    model = train_vendor_risk_model(all_bids, n_tenders)
    clf = model.get("_clf")
    scaler = model.get("_scaler")
    model_type = model["model_type"]

    results = []
    for vid in all_vendor_ids:
        features = _build_vendor_feature_vector(vid, all_bids, n_tenders)
        fv = [features[f] for f in _PRED_FEATURE_NAMES]

        # Compute risk score
        if clf is not None and scaler is not None:
            try:
                import numpy as np
                fv_scaled = scaler.transform([fv])
                proba = clf.predict_proba(fv_scaled)[0]
                # proba[1] = P(risky class)
                risk_score = round(float(proba[1]), 4)
            except Exception:
                risk_score = _heuristic_risk_score(features)
        else:
            # For small datasets, use a hybrid of heuristic and density-based anomaly score
            density_score = 0.0
            if HAS_SKLEARN and len(all_vendor_ids) >= 3:
                try:
                    import numpy as np
                    from sklearn.ensemble import IsolationForest
                    from sklearn.preprocessing import StandardScaler
                    
                    # Gather risk-oriented features for all vendors to construct density space
                    all_fv = []
                    for other_vid in all_vendor_ids:
                        other_feat = _build_vendor_feature_vector(other_vid, all_bids, n_tenders)
                        risk_vec = [
                            float(other_feat.get("blacklist_flag", 0.0)),
                            float(other_feat.get("dq_rate", 0.0)),
                            float(other_feat.get("avg_price_cv", 0.0)),
                            float(other_feat.get("coordination_score", 0.0)),
                            float(other_feat.get("benford_deviation", 0.0)),
                            float(other_feat.get("price_deviation_z", 0.0)),
                            float(abs(other_feat.get("avg_per_ratio", 1.0) - 1.0)),
                            float(other_feat.get("network_centrality", 0.0) if other_feat.get("network_centrality", 0.0) > 0.6 else 0.0)
                        ]
                        all_fv.append(risk_vec)
                    
                    all_fv_arr = np.array(all_fv)
                    scaler_small = StandardScaler()
                    scaled_all = scaler_small.fit_transform(all_fv_arr)
                    
                    # Fit Isolation Forest
                    iforest = IsolationForest(contamination=0.15, random_state=42)
                    iforest.fit(scaled_all)
                    
                    # Decision function: lower values mean more anomalous
                    raw_density_scores = iforest.decision_function(scaled_all)
                    # Min-Max scale to 0-1 range where 1 is highly anomalous
                    min_s, max_s = min(raw_density_scores), max(raw_density_scores)
                    idx_v = all_vendor_ids.index(vid)
                    if max_s != min_s:
                        density_score = float((max_s - raw_density_scores[idx_v]) / (max_s - min_s))
                    else:
                        density_score = 0.0
                except Exception:
                    pass
            
            # Hybrid score: 60% Heuristic + 40% Density-Anomaly Score
            h_score = _heuristic_risk_score(features)
            # Modulate density score contribution when heuristic risk is low to prevent false positives on clean/low-risk vendors
            # If h_score <= 0.1, density_weight is 0.0. It ramps up to 0.4 at h_score = 0.3.
            density_weight = 0.4 * min(1.0, max(0.0, (h_score - 0.1) / 0.2))
            risk_score = round(0.6 * h_score + density_weight * density_score, 4)

        # Classify risk level
        risk_level = (
            "CRITICAL" if risk_score > 0.75 else
            "HIGH"     if risk_score > 0.50 else
            "MODERATE" if risk_score > 0.25 else
            "LOW"
        )

        # Build human-readable risk factors
        risk_factors = []
        if features["blacklist_flag"] > 0:
            risk_factors.append("Vendor is BLACKLISTED")
        if features["dq_rate"] > 0.3:
            risk_factors.append(f"High disqualification rate: {features['dq_rate']:.0%}")
        if features["avg_price_cv"] > 0.25:
            risk_factors.append(f"High price volatility (CV={features['avg_price_cv']:.2f})")
        if features["avg_per_ratio"] < 0.75:
            risk_factors.append(f"Predatory pricing pattern (avg {features['avg_per_ratio']:.2f}x estimate)")
        if features["avg_per_ratio"] > 1.25:
            risk_factors.append(f"Price inflation pattern (avg {features['avg_per_ratio']:.2f}x estimate)")
        if features["win_rate"] > 0.8 and features["bid_count"] >= 3:
            risk_factors.append(f"Suspiciously high win rate: {features['win_rate']:.0%}")

        results.append({
            "vendor_id": vid,
            "company_name": vendor_name_map.get(vid, f"Vendor#{vid}"),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "model_type": model_type,
            "feature_contributions": features,
            "risk_factors": risk_factors if risk_factors else ["No specific risk factors identified"],
        })

    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results

