import os
import sys
from pymongo import MongoClient

def main():
    mongo_url = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_url)
    db = client["gem_tender"]
    
    print("=== TENDERS ===")
    for t in db["tenders"].find():
        print(f"ID: {t.get('id')}, Bid Number: {t.get('bid_number')}, Title: {t.get('title')}, Estimated Value: {t.get('estimated_value')}, EMD Amount: {t.get('emd_amount')}")
        
    print("\n=== BIDS ===")
    for b in db["bids"].find():
        print(f"ID: {b.get('id')}, Tender ID: {b.get('tender_id')}, Vendor ID: {b.get('vendor_id')}, Bid Amount: {b.get('bid_amount')}, Total Amount: {b.get('total_amount')}")

    print("\n=== EVALUATION CRITERIA ===")
    for ec in db["evaluation_criteria"].find():
        print(f"ID: {ec.get('id')}, Tender ID: {ec.get('tender_id')}, Name: {ec.get('name')}, Description: {ec.get('description')}")

if __name__ == "__main__":
    main()
