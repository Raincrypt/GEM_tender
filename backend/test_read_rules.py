import os
import sys

# Add backend to path
sys.path.append(os.path.abspath('backend'))

try:
    from backend.ocr_engine import extract_text_from_file
    from backend.routers.documents import redact_pii

    pdf_path = os.path.join("backend", "uploads", "Rules.pdf")
    print(f"Checking if {pdf_path} exists...")
    if not os.path.exists(pdf_path):
        print(f"Error: {pdf_path} does not exist.")
        sys.exit(1)

    print("Extracting text from Rules.pdf...")
    text = extract_text_from_file(pdf_path)
    print(f"Extracted {len(text)} characters.")
    
    print("\n--- Snippet of first 500 chars ---")
    print(text[:500])
    print("-----------------------------------")

    print("\nRedacting PII...")
    redacted = redact_pii(text)
    print(f"Redacted text has {len(redacted)} characters.")
    
    # Save a temporary copy or verify
    temp_txt_path = os.path.join("backend", "uploads", "pqc_text_test.txt")
    with open(temp_txt_path, "w", encoding="utf-8") as f:
        f.write(redacted)
    print(f"Successfully saved to {temp_txt_path}")

    # Compare with existing pqc_text.txt
    existing_path = os.path.join("backend", "uploads", "pqc_text.txt")
    if os.path.exists(existing_path):
        print(f"Existing pqc_text.txt exists, size: {os.path.getsize(existing_path)} bytes")
    else:
        print("Existing pqc_text.txt does not exist.")
        
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
