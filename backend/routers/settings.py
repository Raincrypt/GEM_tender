# ──────────────────────────────────────────────────────────────────────────────
#  settings.py  — System Path Configuration Router
# ──────────────────────────────────────────────────────────────────────────────

import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from database import mongo_db
import auth

router = APIRouter(prefix="/settings", tags=["Settings"])

class PathSettingsInput(BaseModel):
    rules_pdf_path: str
    tba1_dir_path: str
    tba2_dir_path: str

def get_default_paths() -> dict:
    # Resolve default paths relative to workspace root (parent of backend)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uploads_dir = os.path.join(base_dir, "uploads")
    return {
        "rules_pdf_path": os.path.join(uploads_dir, "Rules.pdf"),
        "tba1_dir_path": os.path.join(uploads_dir, "TBA1"),
        "tba2_dir_path": os.path.join(uploads_dir, "TBA2")
    }

def get_db_path_settings() -> dict:
    defaults = get_default_paths()
    try:
        doc = mongo_db["path_settings"].find_one({"setting_id": "paths"})
        if doc:
            return {
                "rules_pdf_path": doc.get("rules_pdf_path", defaults["rules_pdf_path"]),
                "tba1_dir_path": doc.get("tba1_dir_path", defaults["tba1_dir_path"]),
                "tba2_dir_path": doc.get("tba2_dir_path", defaults["tba2_dir_path"])
            }
    except Exception as e:
        print("[Settings] Failed to fetch path settings from MongoDB, using defaults:", e)
    return defaults

def verify_path(path_str: str, is_file: bool = False) -> dict:
    if not path_str:
        return {"exists": False, "readable": False, "type": "unknown", "error": "Empty path"}
    try:
        exists = os.path.exists(path_str)
        if not exists:
            return {"exists": False, "readable": False, "type": "file" if is_file else "directory", "error": "Path does not exist"}
        
        if is_file:
            is_valid_type = os.path.isfile(path_str)
            readable = os.access(path_str, os.R_OK) if is_valid_type else False
            return {
                "exists": True,
                "readable": readable,
                "type": "file",
                "error": None if is_valid_type else "Path exists but is not a file"
            }
        else:
            is_valid_type = os.path.isdir(path_str)
            readable = os.access(path_str, os.R_OK | os.X_OK) if is_valid_type else False
            return {
                "exists": True,
                "readable": readable,
                "type": "directory",
                "error": None if is_valid_type else "Path exists but is not a directory"
            }
    except Exception as e:
        return {"exists": False, "readable": False, "type": "unknown", "error": str(e)}

@router.get("/paths")
def get_path_config(current_user=Depends(auth.get_current_user)):
    settings = get_db_path_settings()
    
    # Perform real-time validation checks
    rules_status = verify_path(settings["rules_pdf_path"], is_file=True)
    tba1_status = verify_path(settings["tba1_dir_path"], is_file=False)
    tba2_status = verify_path(settings["tba2_dir_path"], is_file=False)
    
    return {
        "settings": settings,
        "verification": {
            "rules_pdf_path": rules_status,
            "tba1_dir_path": tba1_status,
            "tba2_dir_path": tba2_status
        },
        "defaults": get_default_paths()
    }

@router.post("/paths")
def save_path_config(settings: PathSettingsInput, auto_create_dirs: bool = False, current_user=Depends(auth.require_role("Admin"))):
    rules_path = settings.rules_pdf_path.strip()
    tba1_path = settings.tba1_dir_path.strip()
    tba2_path = settings.tba2_dir_path.strip()
    
    # Validate Rules PDF (must be file if it exists, but allow setting non-existent file path if needed)
    if rules_path:
        rules_status = verify_path(rules_path, is_file=True)
        if rules_status["exists"] and not rules_status["readable"]:
            raise HTTPException(status_code=400, detail=f"Rules PDF path is not readable: {rules_status['error']}")

    # Handle directory creations if requested
    for name, path in [("TBA1", tba1_path), ("TBA2", tba2_path)]:
        if path:
            status = verify_path(path, is_file=False)
            if not status["exists"] and auto_create_dirs:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to auto-create {name} directory: {str(e)}")
            elif status["exists"] and not status["readable"]:
                raise HTTPException(status_code=400, detail=f"{name} directory exists but is not readable/accessible: {status['error']}")

    try:
        mongo_db["path_settings"].update_one(
            {"setting_id": "paths"},
            {"$set": {
                "setting_id": "paths",
                "rules_pdf_path": rules_path,
                "tba1_dir_path": tba1_path,
                "tba2_dir_path": tba2_path
            }},
            upsert=True
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")
        
    return {"success": True, "message": "Path configuration saved successfully"}

@router.post("/paths/reset")
def reset_path_config(current_user=Depends(auth.require_role("Admin"))):
    try:
        mongo_db["path_settings"].delete_one({"setting_id": "paths"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database reset failed: {str(e)}")
    return {"success": True, "message": "Paths reset to workspace defaults"}
