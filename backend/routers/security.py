from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import database, models, auth, blockchain
from typing import List, Dict

router = APIRouter(
    prefix="/security",
    tags=["Security & Integrity"]
)

@router.get("/blockchain/verify", response_model=Dict)
def verify_audit_trail(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Cryptographically verifies the entire audit log chain.
    Only Admins can perform a full system integrity check.
    """
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only System Administrators can verify the blockchain audit trail."
        )
    
    is_valid, corrupted_ids = blockchain.verify_chain(db)
    
    total_logs = db.query(models.AuditLog).count()
    
    return {
        "status": "SECURE" if is_valid else "COMPROMISED",
        "total_blocks": total_logs,
        "corrupted_blocks_count": len(corrupted_ids),
        "corrupted_block_ids": corrupted_ids,
        "integrity_score": ((total_logs - len(corrupted_ids)) / total_logs * 100) if total_logs > 0 else 100,
        "verification_method": "SHA-256 Chained Hash Verification"
    }

@router.get("/audit-logs", response_model=List[Dict])
def get_audit_logs(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Fetch all audit logs with their cryptographic hashes.
    """
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied."
        )
    
    logs = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(100).all()
    return [
        {
            "id": l.id,
            "action": l.action,
            "entity": f"{l.entity_type}_{l.entity_id}",
            "details": l.details,
            "user_id": l.user_id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "prev_hash": l.previous_hash[:8] + "..." if l.previous_hash else None,
            "curr_hash": l.current_hash[:8] + "..." if l.current_hash else None
        } for l in logs
    ]

@router.get("/mongodb/status", response_model=Dict)
def get_mongodb_status(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Checks connection to MongoDB, measures round-trip latency, and gathers database statistics.
    Requires Admin privileges.
    """
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied."
        )
    
    import time
    
    start_time = time.time()
    try:
        # Ping the server to check connectivity and measure latency
        database.mongo_client.admin.command('ping')
        latency_ms = round((time.time() - start_time) * 1000, 2)
        
        # Gather server info
        server_info = database.mongo_client.server_info()
        version = server_info.get("version", "Unknown")
        
        # Gathers DB statistics
        collections = database.mongo_db.list_collection_names()
        
        collection_stats = []
        total_docs = 0
        for col_name in collections:
            count = database.mongo_db[col_name].count_documents({})
            total_docs += count
            collection_stats.append({
                "collection": col_name,
                "document_count": count
            })
            
        try:
            db_stats = database.mongo_db.command("dbStats")
            storage_size_bytes = db_stats.get("storageSize", 0)
        except Exception:
            storage_size_bytes = 0
        
        # Human-readable size
        def format_size(size_bytes):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size_bytes < 1024.0:
                    return f"{size_bytes:.2f} {unit}"
                size_bytes /= 1024.0
            return f"{size_bytes:.2f} TB"
            
        return {
            "status": "CONNECTED",
            "latency_ms": latency_ms,
            "version": version,
            "host": database.mongo_client.address[0] if database.mongo_client.address else "localhost",
            "port": database.mongo_client.address[1] if database.mongo_client.address else 27017,
            "collections_count": len(collections),
            "total_documents": total_docs,
            "storage_size": format_size(storage_size_bytes),
            "storage_size_bytes": storage_size_bytes,
            "collections": collection_stats
        }
    except Exception as e:
        return {
            "status": "DISCONNECTED",
            "error": str(e),
            "latency_ms": -1,
            "version": "N/A",
            "host": "N/A",
            "port": 0,
            "collections_count": 0,
            "total_documents": 0,
            "storage_size": "0 B",
            "storage_size_bytes": 0,
            "collections": []
        }


@router.get("/blockchain/blocks", response_model=List[Dict])
def get_blockchain_blocks(
    limit: int = 100,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Fetch audit logs formatted as cryptographically linked blockchain blocks.
    """
    logs = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(limit).all()
    # Total count to calculate index correctly
    total_count = db.query(models.AuditLog).count()
    
    blocks = []
    # If logs are returned newest first (desc), compute block index relative to total_count
    for idx, l in enumerate(logs):
        blocks.append({
            "block_index": total_count - idx,
            "id": l.id,
            "action": l.action,
            "entity": f"{l.entity_type or 'System'}_{l.entity_id or 0}",
            "details": l.details,
            "user_id": l.user_id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            "prev_hash": l.previous_hash or "0" * 64,
            "curr_hash": l.current_hash or "0" * 64
        })
    return blocks


