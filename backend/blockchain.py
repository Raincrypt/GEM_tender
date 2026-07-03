import hashlib
import json
from datetime import datetime
import models

def create_audit_log(db, user_id: int, action: str, entity_type: str, entity_id: int, details: str):
    # Fetch the last log to get its hash
    last_log = db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).first()
    prev_hash = last_log.current_hash if last_log else "0" * 64

    # Explicit timestamp for cryptographic consistency
    current_time = datetime.utcnow()

    # Create new log entry
    log = models.AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address="127.0.0.1",
        previous_hash=prev_hash,
        timestamp=current_time
    )
    
    # Normalize timestamp to string without microseconds for cryptographic consistency
    ts_str = current_time.strftime("%Y-%m-%dT%H:%M:%S")

    # Calculate current hash correctly (simulating a basic blockchain block)
    block_data = {
        "user_id": user_id,
        "action": action,
        "entity": f"{entity_type}_{entity_id}",
        "details": details,
        "prev_hash": prev_hash,
        "timestamp": ts_str
    }
    block_string = json.dumps(block_data, sort_keys=True).encode()
    log.current_hash = hashlib.sha256(block_string).hexdigest()
    
    db.add(log)
    db.flush()
    db.refresh(log)
    return log

def verify_chain(db):
    """
    Enterprise-Grade Verification: Cryptographically validates the entire audit log chain.
    Detects structural breaks (wrong previous hash) and content tampering (hash mismatch).
    """
    logs = db.query(models.AuditLog).order_by(models.AuditLog.id.asc()).all()
    corrupted = []
    prev_hash = "0" * 64
    
    for log in logs:
        # 1. Structural Linkage Check
        if log.previous_hash != prev_hash:
            corrupted.append({
                "id": log.id,
                "reason": "LINK_BREAK",
                "expected_prev": prev_hash,
                "actual_prev": log.previous_hash
            })
            # Even if link is broken, we continue to check content integrity
            
        # 2. Cryptographic Content Check
        # Normalize stored timestamp to match the creation format
        ts_str = log.timestamp.strftime("%Y-%m-%dT%H:%M:%S") if log.timestamp else ""
        
        block_data = {
            "user_id": log.user_id,
            "action": log.action,
            "entity": f"{log.entity_type}_{log.entity_id}",
            "details": log.details,
            "prev_hash": log.previous_hash,
            "timestamp": ts_str
        }
        
        block_string = json.dumps(block_data, sort_keys=True).encode()
        calculated_hash = hashlib.sha256(block_string).hexdigest()
        
        if calculated_hash != log.current_hash:
            # Check if it was already marked for link break
            if not any(c["id"] == log.id for c in corrupted):
                corrupted.append({
                    "id": log.id,
                    "reason": "CONTENT_TAMPERED",
                    "expected_hash": calculated_hash,
                    "actual_hash": log.current_hash
                })
            
        prev_hash = log.current_hash
        
    return len(corrupted) == 0, corrupted


def generate_contract_signing_keys() -> tuple:
    """
    Generates an Elliptic Curve key pair (SECP256R1) for digital signatures.
    Returns (private_key_pem: str, public_key_pem: str)
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")
    
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")
    
    return private_pem, public_pem


def sign_contract(private_key_pem: str, contract_data: dict) -> str:
    """
    Signs contract data using an ECDSA private key.
    Returns signature as hex string.
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None
    )
    
    data_bytes = json.dumps(contract_data, sort_keys=True).encode("utf-8")
    signature = private_key.sign(
        data_bytes,
        ec.ECDSA(hashes.SHA256())
    )
    return signature.hex()


def verify_contract_signature(public_key_pem: str, contract_data: dict, signature_hex: str) -> bool:
    """
    Verifies an ECDSA signature for contract data using a public key.
    Returns True if valid, False otherwise.
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.exceptions import InvalidSignature
    
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8")
        )
        
        data_bytes = json.dumps(contract_data, sort_keys=True).encode("utf-8")
        signature_bytes = bytes.fromhex(signature_hex)
        
        public_key.verify(
            signature_bytes,
            data_bytes,
            ec.ECDSA(hashes.SHA256())
        )
        return True
    except (InvalidSignature, Exception):
        return False

