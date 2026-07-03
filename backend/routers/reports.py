# ──────────────────────────────────────────────────────────────────────────────
#  reports.py  — Aggregator Router for Reports Sub-Modules
# ──────────────────────────────────────────────────────────────────────────────

from fastapi import APIRouter
from routers import reports_core, reports_pqc, reports_advanced

router = APIRouter()
router.include_router(reports_core.router)
router.include_router(reports_pqc.router)
router.include_router(reports_advanced.router)

# Re-export key functions/variables for backward compatibility
from routers.reports_pqc import get_pqc_comparison_data, PQC_RULES
@router.post("/ai-ops/clear-llm-cache")
async def clear_llm_cache():
    import shutil, os
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "llm_cache")
    cleared = 0
    if os.path.isdir(cache_dir):
        for f in os.listdir(cache_dir):
            if f.endswith(".json"):
                os.remove(os.path.join(cache_dir, f))
                cleared += 1
    # Also flush Redis if available
    try:
        import llm_client
        r = llm_client._get_redis_client()
        if r:
            keys = r.keys("llm_cache:*")
            if keys:
                r.delete(*keys)
    except Exception:
        pass
    return {"success": True, "cleared": cleared}