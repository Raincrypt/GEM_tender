# Walkthrough — Phase 3 Advanced AI Features

This document covers all new capabilities implemented in Phase 3.

---

## 1. LLM Response Caching — 24h TTL on File Cache

**File**: [llm_client.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/llm_client.py)

The existing Redis + file-based LLM cache now enforces a **24-hour TTL** on file cache entries. When `_read_cache()` encounters a file older than 86400 seconds (via `os.path.getmtime`), it deletes the stale file and returns `None`, triggering a fresh Ollama call.

- **Result**: No stale AI outputs served after 24h — automatic freshness guarantee.

---

## 2. Vendor DNA Fingerprint Engine

**File**: [vendor_dna.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/vendor_dna.py) *(NEW)*

A behavioral fingerprinting module that profiles every vendor using 4 DNA dimensions:

| DNA Dimension | Description |
|---|---|
| **Price DNA** | 5-bucket normalized histogram of bid-to-estimate ratios |
| **Timing DNA** | 24-bucket hour-of-day bid submission histogram |
| **Co-bid DNA** | Jaccard similarity on co-bidder vendor ID sets |
| **Win DNA** | Category-wise win count distribution |

**Similarity Engine**: Computes composite similarity as `0.5 * price_cosine + 0.2 * timing_cosine + 0.3 * cobid_jaccard`

**Shell Company Detection**: Runs DBSCAN (sklearn or pure-Python fallback) on the pairwise distance matrix. Clusters with ≥2 members are flagged as potential shell company rings.

**Test Result**: ✅ Vendor clone pair scored 80% similarity vs 50% for unrelated pair. 1 shell cluster correctly detected.

---

## 3. Predictive Vendor Risk Model

**File**: [anomaly_detector.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/anomaly_detector.py)

An ML-powered risk scoring system using **12 predictive features** (expanded from 8 baseline features to incorporate network graph, timing coordination, Benford deviations, and pricing distance signals):

| Feature | Description |
|---|---|
| `bid_count` | Total bids submitted |
| `win_rate` | Fraction of bids won |
| `avg_price_cv` | Price volatility (coefficient of variation) |
| `avg_per_ratio` | Average price-to-estimate ratio |
| `dq_rate` | Disqualification rate |
| `blacklist_flag` | 1 if blacklisted |
| `avg_delivery_days` | Average delivery period |
| `multi_tender_rate` | Tender participation rate |
| `network_centrality` | Degree centrality within the co-bidding collusion graph |
| `coordination_score` | Submission timestamp coordinate burstiness & entropy rating |
| `benford_deviation` | Digit-level deviation score of vendor bid amounts from Benford's Law |
| `price_deviation_z` | Z-score pricing distance of the vendor's average bid relative to the tender estimation |

* **>=10 vendors**: Trains an **Ensemble Soft-Voting Classifier** (comprising Gradient Boosting + Random Forest + Logistic Regression) with hyperparameter grid search (`GridSearchCV`) and cross-validation (`StratifiedKFold`).
* **<10 vendors (Fallback)**: Uses a hybrid of heuristic rules (60% weight) and an `IsolationForest` density-based anomaly score (40% weight) trained on risk-oriented features and smoothly modulated to prevent clean vendors from getting false positive anomalies.
* Returns ranked list with `risk_score`, `risk_level`, and human-readable `risk_factors`.

**Test Result**: ✅ Blacklisted/DQ vendor scored 0.7837 (CRITICAL), clean vendor scored 0.0600 (LOW). Sorted correctly.

---

## 4. Autonomous Compliance Sentinel — Policy Guardian Γ

**File**: [ai_swarm_engine.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/ai_swarm_engine.py)

New 8th AI agent added to the swarm registry. Validates tender documents against **8 mandatory GEM/CVC clauses**:

| Clause ID | Name | Policy Reference |
|---|---|---|
| GEM-EMD | EMD / Bid Security | CVC Circular 2023/01 |
| GEM-LD | Liquidated Damages | GEM Rule 9.3 |
| GEM-INTEGRITY | Integrity Pact | CVC Circular 2004/07 |
| GEM-WARRANTY | Warranty / AMC | GEM Rule 12.1 |
| GEM-MSME | MSME Preference | MSME Order 2012 |
| GEM-MII | Make in India | DPIIT Order 2017 |
| GEM-GST | GST Compliance | GST Act 2017 |
| GEM-DEBARMENT | Debarment Check | GEM Rule 5.2 |

Also checks:
- **CVC flags**: single-bid, nomination basis, advance payment without BG
- **MSME waivers**: EMD exemption, experience/turnover waiver for registered MSMEs

**API**: `POST /ai-ops/compliance-scan` with `{ document_text, tender_title, vendor_profile }`

**Test Result**: ✅ Full document scored 100%, minimal scored 0%. MSME vendor correctly received 3 waivers.

---

## 5. Real-Time EWMA Anomaly Stream (SSE)

**File**: [reports_advanced.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/routers/reports_advanced.py)

**Endpoint**: `GET /reports/anomaly-stream`

Server-Sent Events stream that:
1. Loads all bids from DB sorted by submission time
2. Computes EWMA control chart (span=5) in bulk
3. Streams each bid as a JSON event at ~12 events/second including:
   - `ewma_value`, `ucl` (upper control limit), `lcl`, `signal` (UPPER_BREACH / LOWER_BREACH / NORMAL / ANOMALY)
4. Closes cleanly with `event: end` after all bids processed

**Test Result**: ✅ Spike at position 10 correctly flagged as anomaly.

---

## 6. New Frontend Pages & Panels

### `predictive_risk.html` *(NEW)*
- **Vendor Risk Heatmap**: Animated horizontal bars for all vendors, color-coded by risk level
- **Search & Filter**: By vendor name or risk level
- **Feature Importance Chart**: Bar chart showing which features drive the model
- **EWMA Live Canvas Chart**: Real-time anomaly feed via SSE with UCL/LCL control bands, anomaly dots
- **Shell Company Clusters**: DBSCAN cluster cards with similarity scores and member chips
- **Vendor Detail Modal**: Full breakdown of feature contributions per vendor
- **Demo Mode**: Falls back gracefully with synthetic data when backend is offline

### `dashboard.html` — Intelligence Telemetry Panel
Added collapsible **Intelligence Telemetry** panel at bottom:
- Fetches `/reports/predictive-vendor-risk` and renders top-5 risk vendors
- Summary badge showing critical/high counts and model type
- Quick Action links to: Predictive Risk Dashboard, DNA Fingerprint Analysis, Cartel Network Graph
- Shimmer skeleton loading state
- Refresh button + Full Report link

---

## 7. New API Endpoints Summary

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/reports/predictive-vendor-risk` | ML risk scores for all vendors |
| `GET` | `/reports/vendor-dna-analysis` | DNA fingerprint + shell clusters |
| `GET` | `/reports/anomaly-stream` | SSE EWMA bid anomaly stream |
| `GET` | `/ai-ops/vendor-risk/predict` | Same as above via ai-ops router |
| `GET` | `/ai-ops/vendor-dna` | Same as above via ai-ops router |
| `POST` | `/ai-ops/compliance-scan` | Policy Guardian Γ document scan |

---

## 8. Phase 3 Test Results

```
Total: 6/6 tests passed ✅ ALL PHASE 3 TESTS PASSED

[PASS] LLM Cache 24h TTL
[PASS] Vendor DNA Engine — clone similarity 80% vs 50%, 1 cluster detected
[PASS] Predictive Risk Model — blacklisted vendor scored 0.7837, clean vendor 0.0600
[PASS] Compliance Sentinel — full doc 100%, minimal doc 0%, 3 MSME waivers
[PASS] EWMA Detection — spike at index 10 flagged as anomaly
[PASS] Agent Registry — 9 agents including COMPLIANCE (Policy Guardian Γ)
```

---

## 9. Conflict-of-Interest Swarm Agent — Kinship Sentinel X

**Files**: [ai_swarm_engine.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/ai_swarm_engine.py), [ai_ops.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/routers/ai_ops.py)

A new swarm member, **Kinship Sentinel X** (`CONFLICT_OF_INTEREST`), was introduced. It scans sets of bidding vendors and cross-checks metadata for kinship overlaps:
* **IP overlaps**: matching exact IP address or shared `/24` subnet.
* **Email overlaps**: matching domains (excluding public hosts).
* **Personnel overlaps**: matching directorships.
* **Structural overlaps**: matching addresses and contact phone numbers.
* **Verdict**: Instructs Llama 3.1 8B to summarize the overlap risk and generate a narrative verdict.

**API**: `POST /ai-ops/conflict-scan` with `{ bids_data }`

---

## 10. Louvain Community Detection (Cartel Graphs)

**File**: [reports_core.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/routers/reports_core.py)

Upgraded the `/cartel-graph` endpoint to build a NetworkX weighted Graph (where weight corresponds to collusion levels) and execute the **Louvain community detection** algorithm. 
* Automatically groups vendors into discrete ring community structures.
* Appends `community_id` and list of `community_members` to each node.
* Re-colors graph node groups in the JSON payload so the frontend visualizer displays distinct clusters automatically.

---

## 11. ECDSA Contract Signatures (Blockchain verification)

**File**: [blockchain.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/blockchain.py)

Transitioned contract logging to use asymmetric **ECDSA (Elliptic Curve Digital Signature Algorithm)** signatures using the SECP256R1 curve.
* Generates PEM private and public key pairs.
* Signs contract dictionaries to create secure hex signatures.
* Verifies signatures with public keys, rejecting any tampered payload fields (such as modified award amount).

---

## 12. Qdrant Vector Database Integration

**Files**: [rag_engine.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/rag_engine.py), [requirements.txt](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/requirements.txt)

Implemented support for **Qdrant** alongside the existing FAISS database.
* Activated via `.env` parameter `RAG_VECTOR_DB=qdrant`.
* Uses `qdrant-client` to connect to local persistent storage (saving to `./qdrant_db/`) or remote endpoints.
* Uses the new Qdrant **Unified Query API** (`query_points`) for vector search and pre-filters queries dynamically.

---

## 13. Advanced Upgrades Verification Results

**Test File**: [test_advanced_features_upgrade.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/test_advanced_features_upgrade.py)

Executing the test suite validates that all six advanced systems are fully functional:
```
Ran 6 tests in 19.045s

OK
[TEST] Verifying Conflict-of-Interest Swarm Agent...
[OK] Conflict-of-Interest Swarm Agent verified successfully.

[TEST] Verifying ECDSA asymmetric contract signature verification...
[OK] ECDSA signatures generated and verified successfully.

[TEST] Verifying AI clause explanation & citation...
[OK] AI clause explanation & citation verified successfully.

[TEST] Verifying Louvain community detection in cartel report...
[OK] Louvain clustering in Cartel Graph verified successfully.

[TEST] Verifying LLM structured rule extraction...
[OK] LLM structured rule extraction verified successfully.

[TEST] Verifying Qdrant local database indexing & retrieval...
[OK] Qdrant RAG ingestion and retrieval verified successfully.
```

---

## 14. Frontend Integration & E2E Verification

**File**: [cartel.html](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/frontend/cartel.html)

The new advanced features are fully integrated into the cartel network graph UI:
1. **Dynamic Color Toggles**: Users can switch between coloring nodes by **Risk Status** (Normal, Suspicious, Blacklisted) and **Louvain Rings** (distinct ring colors for each community cluster).
2. **NetworkX Centrality Panel**: Selecting a vendor node displays its computed **Degree Centrality**, **Betweenness Centrality**, and **Eigenvector Centrality** metrics alongside its bidding ring member list.
3. **Kinship Sentinel X Swarm Scan**: Added a button to execute a real-time Conflict-of-Interest scan on the entire community ring of the selected vendor. The UI triggers the backend `POST /ai-ops/conflict-scan` endpoint and displays the agent's forensic narrative and specific metadata overlap links.

---

## 15. Centralized OCR Caching & Retrieval Optimization

**Files**: [ocr_engine.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/ocr_engine.py), [test_ocr_cache.py](file:///c:/Users/Mrinmoy/Downloads/tender%20(2)/tender/backend/test_ocr_cache.py) *(NEW)*

To minimize redundant CPU/GPU workload and accelerate document evaluation cycles, a centralized caching mechanism has been added to the multi-engine OCR cascade:
1. **Unified State Caching**: Generates a unique SHA256 key matching the file path, file size, and file modification time (`mtime`).
2. **Dual-Tier Cache Store**: Attempts lookup in Redis first for high-performance distributed key-value storage, and falls back to local persistent JSON file cache under `backend/ocr_cache/`.
3. **Transparent Execution**: Intercepts `extract_text_from_file(file_path)` at call time to instantly bypass the multi-engine cascade (Vision OCR + Tesseract) on cache hit.

**Test Result**: ✅ All test cases passed successfully in `test_ocr_cache.py`.

