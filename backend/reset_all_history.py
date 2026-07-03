import os
import sys
import shutil
import redis
from pymongo import MongoClient

# Configure UTF-8 encoding for standard output on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add current directory to python path if run from root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, mongo_client
import models
import auth

def reset_all_history():
    print("=== STARTING FULL HISTORY RESET ===")

    # 1. MongoDB Database Resets
    print("\n[1/6] Resetting MongoDB database...")
    try:
        db_names = ["gem_tender", "gem_tender_db", "gem_tender_enterprise"]
        for db_name in db_names:
            mongo_client.drop_database(db_name)
            print(f"SUCCESS: Dropped MongoDB database: {db_name}")
        
        # Recreate default admin user
        db = SessionLocal()
        admin = models.User(
            username="admin", 
            email="admin@iocl.in", 
            full_name="IOCL Admin",
            hashed_password=auth.get_password_hash("admin123"), 
            role="Admin"
        )
        db.add(admin)
        db.commit()
        db.close()
        print("SUCCESS: Default admin user recreated in 'gem_tender'.")
    except Exception as e:
        print(f"ERROR: Error resetting MongoDB: {e}")

    # 2. Deleting stale SQLite files
    print("\n[2/6] Deleting stale SQLite database files...")
    for base_path in ["gem_tender.db", "./backend/gem_tender.db", "./gem_tender.db"]:
        for ext in ["", "-shm", "-wal"]:
            path = base_path + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"SUCCESS: Removed stale SQLite file: {path}")
                except Exception as e:
                    print(f"ERROR: Could not remove SQLite file {path}: {e}")

    # 3. Redis Cache Clear
    print("\n[3/6] Clearing Redis cache...")
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(redis_url)
        r.flushall()
        print("SUCCESS: Redis cache flushed successfully.")
    except Exception as e:
        print(f"WARNING: Redis clear skipped or failed: {e}")

    # 4. Clean Dynamic Uploads
    print("\n[4/6] Cleaning dynamic uploads...")
    uploads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
    if os.path.exists(uploads_dir):
        deleted_count = 0
        for item in os.listdir(uploads_dir):
            item_path = os.path.join(uploads_dir, item)
            # Delete dynamically uploaded vendor documents
            if os.path.isfile(item_path) and item.startswith("bid_"):
                try:
                    os.remove(item_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"ERROR: Error deleting upload file {item}: {e}")
        print(f"SUCCESS: Cleaned {deleted_count} dynamic upload files (bid_*).")
    else:
        print("SUCCESS: Uploads directory does not exist.")

    # 5. Clean Generated Smart Contracts
    print("\n[5/6] Cleaning generated smart contracts...")
    contracts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contracts")
    if os.path.exists(contracts_dir):
        deleted_contracts = 0
        for item in os.listdir(contracts_dir):
            item_path = os.path.join(contracts_dir, item)
            if os.path.isfile(item_path) and item.endswith(".sol"):
                try:
                    os.remove(item_path)
                    deleted_contracts += 1
                except Exception as e:
                    print(f"ERROR: Error deleting contract file {item}: {e}")
        print(f"SUCCESS: Cleaned {deleted_contracts} generated Solidity smart contracts.")
    else:
        print("SUCCESS: Contracts directory does not exist.")

    # 6. Clean Email Logs
    print("\n[6/6] Cleaning email logs...")
    email_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_logs.txt")
    if os.path.exists(email_log_path):
        try:
            os.remove(email_log_path)
            print("SUCCESS: Deleted email_logs.txt.")
        except Exception as e:
            print(f"ERROR: Error deleting email_logs.txt: {e}")
    else:
        print("SUCCESS: No email_logs.txt found.")

    print("\n=== HISTORY RESET PROCESS COMPLETE ===")

if __name__ == "__main__":
    reset_all_history()
