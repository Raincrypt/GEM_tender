"""
GEM Vendor DNA Fingerprint Engine v1.0
=======================================
Identifies vendors by unique behavioral fingerprints derived from:
  - Price DNA   : distribution of bid-to-estimate ratios
  - Timing DNA  : hour-of-day bid submission histogram
  - Co-bid DNA  : set of co-bidder relationships
  - Win DNA     : pattern of tender categories won

Enables:
  - Shell company ring detection (DBSCAN on DNA similarity matrix)
  - Behavioral clone matching across tender cycles
  - Cartel fingerprint correlation scoring
"""

import math
import hashlib
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Any


# ─────────────────────────────────────────────────────────────────
#  PRICE DNA EXTRACTION
# ─────────────────────────────────────────────────────────────────
_PRICE_BUCKETS = [
    (0.0, 0.7),   # Predatory / severely underbid
    (0.7, 0.9),   # Competitive undercut
    (0.9, 1.05),  # At-estimate (market-normal)
    (1.05, 1.3),  # Overpriced
    (1.3, 9999),  # Grossly inflated
]

def _price_bucket(ratio: float) -> int:
    for i, (lo, hi) in enumerate(_PRICE_BUCKETS):
        if lo <= ratio < hi:
            return i
    return len(_PRICE_BUCKETS) - 1


# ─────────────────────────────────────────────────────────────────
#  VENDOR DNA BUILDER
# ─────────────────────────────────────────────────────────────────
def extract_vendor_dna(
    vendor_id: Any,
    all_bids: List[dict],
    all_tenders: List[dict],
) -> dict:
    """
    Build a behavioral fingerprint (DNA) for a vendor.

    Args:
        vendor_id: The vendor's unique ID
        all_bids:  List of bid dicts (all bids across all tenders).
                   Each dict must have keys: vendor_id, total_amount, tender_id,
                   submitted_at (optional), status (optional).
        all_tenders: List of tender dicts with id, estimated_value, title, category.

    Returns:
        dict with keys:
          - vendor_id
          - price_dna      : list[5 floats] — normalized price-bucket histogram
          - timing_dna     : list[24 floats] — normalized hour-of-day histogram
          - cobid_dna      : list[int] — sorted list of co-bidder vendor IDs
          - win_dna        : dict[category -> win_count]
          - bid_count      : int
          - win_count      : int
          - avg_per        : float — average price-to-estimate ratio
          - fingerprint_hash : str — SHA256 of the price+timing DNA (identity probe)
    """
    tender_map = {t["id"]: t for t in all_tenders}

    my_bids = [b for b in all_bids if b.get("vendor_id") == vendor_id]

    # ── Price DNA ──────────────────────────────────────────────
    price_hist = [0] * len(_PRICE_BUCKETS)
    per_values = []
    for b in my_bids:
        tid = b.get("tender_id")
        t = tender_map.get(tid, {})
        est = t.get("estimated_value") or 0
        amt = b.get("total_amount") or 0
        if est > 0 and amt > 0:
            ratio = amt / est
            per_values.append(ratio)
            price_hist[_price_bucket(ratio)] += 1

    price_total = sum(price_hist) or 1
    price_dna = [round(c / price_total, 4) for c in price_hist]
    avg_per = round(sum(per_values) / max(len(per_values), 1), 4)

    # ── Timing DNA (24-hour histogram) ────────────────────────
    hour_hist = [0] * 24
    for b in my_bids:
        ts_str = b.get("submitted_at")
        if ts_str:
            try:
                from datetime import datetime
                # Handle ISO format strings
                if isinstance(ts_str, str):
                    dt_clean = ts_str.replace("Z", "").split("+")[0].split(".")[0]
                    dt = datetime.fromisoformat(dt_clean)
                else:
                    dt = ts_str
                hour_hist[dt.hour] += 1
            except Exception:
                pass

    hour_total = sum(hour_hist) or 1
    timing_dna = [round(c / hour_total, 4) for c in hour_hist]

    # ── Co-bid DNA ────────────────────────────────────────────
    cobid_vendors = set()
    # Build per-tender vendor sets
    tender_participants: Dict[Any, set] = defaultdict(set)
    for b in all_bids:
        tender_participants[b.get("tender_id")].add(b.get("vendor_id"))

    for b in my_bids:
        tid = b.get("tender_id")
        for other_vid in tender_participants.get(tid, set()):
            if other_vid != vendor_id:
                cobid_vendors.add(other_vid)

    cobid_dna = sorted(cobid_vendors)

    # ── Win DNA ───────────────────────────────────────────────
    win_dna: Dict[str, int] = {}
    for b in my_bids:
        if (b.get("status") or "").lower() in ("awarded", "won", "l1"):
            tid = b.get("tender_id")
            t = tender_map.get(tid, {})
            cat = t.get("category") or t.get("title", "Unknown")[:30]
            win_dna[cat] = win_dna.get(cat, 0) + 1

    # ── Fingerprint Hash ──────────────────────────────────────
    hash_payload = f"{price_dna}|{timing_dna[:12]}"
    fingerprint_hash = hashlib.sha256(hash_payload.encode()).hexdigest()[:16]

    return {
        "vendor_id": vendor_id,
        "price_dna": price_dna,
        "timing_dna": timing_dna,
        "cobid_dna": cobid_dna,
        "win_dna": win_dna,
        "bid_count": len(my_bids),
        "win_count": len([b for b in my_bids if (b.get("status") or "").lower() in ("awarded", "won", "l1")]),
        "avg_per": avg_per,
        "fingerprint_hash": fingerprint_hash,
    }


# ─────────────────────────────────────────────────────────────────
#  COSINE SIMILARITY BETWEEN DNA VECTORS
# ─────────────────────────────────────────────────────────────────
def _cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Cosine similarity between two equal-length numeric vectors."""
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a ** 2 for a in vec_a))
    norm_b = math.sqrt(sum(b ** 2 for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return round(dot / (norm_a * norm_b), 4)


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard index between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return round(intersection / union, 4) if union > 0 else 0.0


def compute_dna_similarity(dna_a: dict, dna_b: dict) -> dict:
    """
    Compute composite behavioral similarity between two vendor DNA fingerprints.

    Returns:
        dict with:
          - price_sim   : float 0-1 (cosine of price distribution)
          - timing_sim  : float 0-1 (cosine of hour-of-day distribution)
          - cobid_sim   : float 0-1 (Jaccard of co-bidder sets)
          - composite   : float 0-1 (weighted average)
          - risk_level  : "CRITICAL" / "HIGH" / "MODERATE" / "LOW"
          - is_clone    : bool — True if composite > 0.85
    """
    price_sim = _cosine_similarity(dna_a["price_dna"], dna_b["price_dna"])
    timing_sim = _cosine_similarity(dna_a["timing_dna"], dna_b["timing_dna"])
    cobid_sim = _jaccard_similarity(set(dna_a["cobid_dna"]), set(dna_b["cobid_dna"]))

    # Weighted composite: price behavior is most diagnostic
    composite = round(
        0.50 * price_sim + 0.20 * timing_sim + 0.30 * cobid_sim, 4
    )

    risk_level = (
        "CRITICAL" if composite > 0.85 else
        "HIGH"     if composite > 0.70 else
        "MODERATE" if composite > 0.50 else
        "LOW"
    )

    return {
        "price_sim": price_sim,
        "timing_sim": timing_sim,
        "cobid_sim": cobid_sim,
        "composite": composite,
        "risk_level": risk_level,
        "is_clone": composite > 0.85,
    }


# ─────────────────────────────────────────────────────────────────
#  SHELL COMPANY CLUSTER DETECTION (DBSCAN)
# ─────────────────────────────────────────────────────────────────
def find_shell_company_clusters(
    all_dna: List[dict],
    eps: float = 0.30,          # DBSCAN epsilon (distance threshold = 1 - similarity)
    min_samples: int = 2,       # Min vendors to form a cluster
) -> dict:
    """
    Run DBSCAN clustering on vendor DNA similarity to find shell company rings.

    Each pair's distance = 1 - composite_similarity.
    Clusters with 2+ members are flagged as potential shell company rings.

    Args:
        all_dna: List of vendor DNA dicts (output of extract_vendor_dna)
        eps:     DBSCAN distance threshold (lower = stricter)
        min_samples: Minimum cluster members

    Returns:
        dict with:
          - clusters: list of cluster dicts
          - noise_vendors: list of vendor_ids with no cluster
          - summary: overall stats
    """
    n = len(all_dna)
    if n < 2:
        return {"clusters": [], "noise_vendors": [d["vendor_id"] for d in all_dna], "summary": {"total_vendors": n, "clusters_found": 0}}

    # Build pairwise distance matrix
    dist_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            sim = compute_dna_similarity(all_dna[i], all_dna[j])["composite"]
            dist = round(1.0 - sim, 4)
            dist_matrix[i][j] = dist
            dist_matrix[j][i] = dist

    # Try scikit-learn DBSCAN first
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN

        dist_arr = np.array(dist_matrix)
        db = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed")
        labels = db.fit_predict(dist_arr).tolist()

    except ImportError:
        # Pure-Python DBSCAN fallback
        labels = _pure_dbscan(dist_matrix, eps, min_samples)

    # Build cluster output
    cluster_map: Dict[int, List[int]] = defaultdict(list)
    for idx, label in enumerate(labels):
        cluster_map[label].append(idx)

    clusters = []
    noise_vendors = []

    for label, indices in cluster_map.items():
        if label == -1:
            noise_vendors = [all_dna[i]["vendor_id"] for i in indices]
            continue

        members = [all_dna[i] for i in indices]
        # Compute average intra-cluster similarity
        pairs = []
        for ii in range(len(indices)):
            for jj in range(ii + 1, len(indices)):
                sim = 1.0 - dist_matrix[indices[ii]][indices[jj]]
                pairs.append(sim)
        avg_sim = round(sum(pairs) / max(len(pairs), 1), 4)

        # Assess risk
        risk = "CRITICAL" if avg_sim > 0.85 else "HIGH" if avg_sim > 0.70 else "MODERATE"

        clusters.append({
            "cluster_id": label,
            "member_count": len(members),
            "vendor_ids": [m["vendor_id"] for m in members],
            "avg_behavioral_similarity": avg_sim,
            "risk_level": risk,
            "evidence": f"Behavioral similarity {avg_sim:.0%} — bid pattern clustering, co-bidder overlap, and price strategy alignment detected.",
            "members": [
                {
                    "vendor_id": m["vendor_id"],
                    "bid_count": m["bid_count"],
                    "win_count": m["win_count"],
                    "avg_per": m["avg_per"],
                    "fingerprint_hash": m["fingerprint_hash"],
                }
                for m in members
            ],
        })

    clusters.sort(key=lambda c: c["avg_behavioral_similarity"], reverse=True)

    return {
        "clusters": clusters,
        "noise_vendors": noise_vendors,
        "summary": {
            "total_vendors": n,
            "clusters_found": len(clusters),
            "vendors_in_clusters": sum(c["member_count"] for c in clusters),
            "noise_vendors_count": len(noise_vendors),
            "highest_risk": clusters[0]["risk_level"] if clusters else "NONE",
        },
    }


def _pure_dbscan(dist_matrix: list, eps: float, min_samples: int) -> list:
    """Pure-Python DBSCAN on a precomputed distance matrix."""
    n = len(dist_matrix)
    labels = [-1] * n
    visited = [False] * n
    cluster_id = 0

    def neighbors(idx):
        return [j for j in range(n) if dist_matrix[idx][j] <= eps]

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        nbrs = neighbors(i)
        if len(nbrs) < min_samples:
            continue
        labels[i] = cluster_id
        seed = list(nbrs)
        k = 0
        while k < len(seed):
            j = seed[k]
            if not visited[j]:
                visited[j] = True
                jnbrs = neighbors(j)
                if len(jnbrs) >= min_samples:
                    seed.extend(jnbrs)
            if labels[j] == -1:
                labels[j] = cluster_id
            k += 1
        cluster_id += 1

    return labels


# ─────────────────────────────────────────────────────────────────
#  FULL DNA ANALYSIS PIPELINE
# ─────────────────────────────────────────────────────────────────
def run_full_dna_analysis(
    all_bids: List[dict],
    all_tenders: List[dict],
    all_vendor_ids: List[Any],
    vendor_name_map: Optional[Dict[Any, str]] = None,
) -> dict:
    """
    Run the complete DNA fingerprinting and shell company detection pipeline.

    Args:
        all_bids: All bid records with vendor_id, tender_id, total_amount, submitted_at, status
        all_tenders: All tender records with id, estimated_value, category, title
        all_vendor_ids: List of all vendor IDs to profile
        vendor_name_map: Optional dict {vendor_id: company_name}

    Returns:
        dict with vendor_profiles, similarity_matrix, shell_clusters, summary
    """
    vendor_name_map = vendor_name_map or {}

    # Build DNA for every vendor
    vendor_dna = []
    for vid in all_vendor_ids:
        dna = extract_vendor_dna(vid, all_bids, all_tenders)
        dna["company_name"] = vendor_name_map.get(vid, f"Vendor#{vid}")
        vendor_dna.append(dna)

    # Build pairwise similarity matrix (upper triangle)
    similarity_pairs = []
    for i in range(len(vendor_dna)):
        for j in range(i + 1, len(vendor_dna)):
            sim = compute_dna_similarity(vendor_dna[i], vendor_dna[j])
            similarity_pairs.append({
                "vendor_a_id": vendor_dna[i]["vendor_id"],
                "vendor_a_name": vendor_dna[i]["company_name"],
                "vendor_b_id": vendor_dna[j]["vendor_id"],
                "vendor_b_name": vendor_dna[j]["company_name"],
                **sim,
            })

    similarity_pairs.sort(key=lambda x: x["composite"], reverse=True)

    # Run DBSCAN shell company detection
    clusters_result = find_shell_company_clusters(vendor_dna)

    # Add company names to cluster members
    for cluster in clusters_result["clusters"]:
        for member in cluster["members"]:
            member["company_name"] = vendor_name_map.get(member["vendor_id"], f"Vendor#{member['vendor_id']}")

    return {
        "vendor_profiles": vendor_dna,
        "top_similarity_pairs": similarity_pairs[:20],
        "shell_clusters": clusters_result,
        "total_pairs_analyzed": len(similarity_pairs),
        "high_risk_pairs": [p for p in similarity_pairs if p["risk_level"] in ("HIGH", "CRITICAL")],
    }
