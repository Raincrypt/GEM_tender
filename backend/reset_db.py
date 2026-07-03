"""
GEM Tender — Database Reset Utility
Run this script to drop all tables and recreate them from scratch.
WARNING: This deletes ALL data. Use only in development.
"""
import os
import sys

# Configure UTF-8 encoding for standard output on Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def confirm():
    ans = input("\n[WARNING] This will DELETE all data in the database!\n"
                "   Type 'YES' to confirm: ").strip()
    return ans == "YES"

if __name__ == "__main__":
    if "--force" not in sys.argv:
        if not confirm():
            print("Aborted.")
            sys.exit(0)

    print("\n[RESET] Resetting MongoDB database...")

    import database
    import models
    import auth
    from database import mongo_db

    collections = [
        "users", "vendors", "tenders", "evaluation_criteria", "bids", 
        "bid_scores", "bid_documents", "purchase_orders", "delivery_records", 
        "payment_records", "audit_logs", "pqc_evaluations"
    ]
    for col in collections:
        mongo_db[col].delete_many({})
        print(f"[SUCCESS] Collection '{col}' cleared.")

    db = database.MongoSession(mongo_db)
    admin = models.User(
        username="admin", 
        email="admin@iocl.in", 
        full_name="IOCL Admin",
        hashed_password=auth.get_password_hash("admin123"), 
        role="Admin"
    )
    db.add(admin)
    db.commit()
    print("[SUCCESS] Default admin user recreated.")

    # Remove stale SQLite database files if they exist in backend or root
    for base_path in ["gem_tender.db", "./backend/gem_tender.db", "./gem_tender.db"]:
        for ext in ["", "-shm", "-wal"]:
            path = base_path + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"[SUCCESS] Removed stale SQLite file: {path}")
                except Exception as e:
                    print(f"Could not remove SQLite file {path}: {e}")

    print("\n[COMPLETE] Database reset complete. Run `python seed_iocl.py` to repopulate.")
