import os
import sys
from pymongo import MongoClient

def main():
    mongo_url = os.getenv("MONGO_URL", "mongodb://127.0.0.1:27017")
    client = MongoClient(mongo_url)
    db = client["gem_tender"]
    
    output_lines = []
    
    output_lines.append("=== SEARCHING MONGODB FOR 40.00 / 40.00L / \u20b940.00L ===")
    
    # Let's inspect vendors
    vendors = {v["id"]: v["company_name"] for v in db["vendors"].find()}
    output_lines.append(f"Loaded {len(vendors)} vendors.")
    
    # Query bid documents
    docs = list(db["bid_documents"].find())
    output_lines.append(f"Loaded {len(docs)} bid documents from MongoDB.")
    
    queries = ["40.00L", "\u20b940.00L", "40.00", "40L", "40,00,000", "4000000", "40.00 Lakh", "40 Lakh"]
    
    found_any = False
    for doc in docs:
        bid_id = doc.get("bid_id")
        # Find vendor name
        bid = db["bids"].find_one({"id": bid_id})
        vendor_name = "Unknown"
        if bid:
            vendor_id = bid.get("vendor_id")
            vendor_name = vendors.get(vendor_id, f"Vendor {vendor_id}")
            
        text = doc.get("ocr_extracted_text") or ""
        doc_type = doc.get("document_type") or "Unknown"
        file_path = doc.get("file_path") or "Unknown"
        
        matches = []
        for q in queries:
            if q.lower() in text.lower():
                matches.append(q)
                
        if matches:
            found_any = True
            output_lines.append(f"\nMatch found in vendor: {vendor_name}")
            output_lines.append(f"Document type: {doc_type}, Path: {file_path}")
            output_lines.append(f"Matching query terms: {matches}")
            
            # Print surrounding lines for context
            lines = text.split("\n")
            for idx, line in enumerate(lines):
                for q in queries:
                    if q.lower() in line.lower():
                        # print context around matching line
                        start = max(0, idx - 2)
                        end = min(len(lines), idx + 3)
                        output_lines.append(f"--- Context (lines {start} to {end}) ---")
                        for i in range(start, end):
                            prefix = ">>> " if i == idx else "    "
                            output_lines.append(f"{prefix}{lines[i]}")
                        output_lines.append("---------------------------------------")
                        break

    if not found_any:
        output_lines.append("No documents matched search terms.")
        
    with open("search_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    print("Search results written to search_results.txt successfully.")

if __name__ == "__main__":
    main()
