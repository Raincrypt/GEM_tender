import json
import os
import re

def test():
    with open("backend/uploads/TBA1/ocr_cache.json", "r", encoding="utf-8") as f:
        raw_cache = json.load(f)
    cache = {k.replace("\\", "/").split("/")[-1].upper(): v for k, v in raw_cache.items()}
        
    tba1_dir = os.path.join("backend", "uploads", "TBA1")
    vendors = sorted(os.listdir(tba1_dir))
    
    for v in vendors:
        v_path = os.path.join(tba1_dir, v)
        if not os.path.isdir(v_path):
            continue
            
        print(f"\n==================== VENDOR: {v} ====================")
        v_files = sorted(os.listdir(v_path))
        
        all_text = ""
        for f in v_files:
            if not f.lower().endswith(".pdf"):
                continue
            # Handle key case flexibility
            text = cache.get(f, cache.get(f.upper(), ""))
            all_text += "\n" + text
            
        # Parse LED Wall Specs
        size_match = re.search(r'(?:IAC130|IAC\s*130|130\s*(?:inch|"|in|\'))', all_text, re.IGNORECASE)
        pitch_match = re.search(r'(?:p|pixel\s*pitch\s*)?1\.5\s*(?:mm)?(?!\d)', all_text, re.IGNORECASE)
        res_match = re.search(r'(?:1920\s*[xX\u00d7]\s*1080|\bFHD\b|FULL[\s\-]?HD)', all_text, re.IGNORECASE)
        diode_match = re.search(r'\b(?:SMD|COB|GOB)\b', all_text, re.IGNORECASE)
        led_contrast_match = re.search(r'(?<![\d])(?:[5-9][0-9]{3}|[1-9][0-9]{4,})\s*:\s*1(?![0-9])', all_text, re.IGNORECASE)
        led_refresh_match = re.search(r'(?:3840|7680)\s*(?:Hz|Refresh)', all_text, re.IGNORECASE)
        
        # Parse LFD Specs
        lfd_size_match = re.search(r'(?:BE85|LH85|85\s*(?:inch|"|in|\'))', all_text, re.IGNORECASE)
        lfd_res_match = re.search(r'(?:3840\s*[xX\u00d7]\s*2160|\b4K\b|\bUHD\b)', all_text, re.IGNORECASE)
        lfd_brightness_match = re.search(r'(?:25[0-9]|[3-9]\d{2})\s*(?:nit|cd)', all_text, re.IGNORECASE)
        lfd_contrast_match = re.search(r'(?<![\d])(?:4[7-9][0-9]{2}|[5-9][0-9]{3}|[1-9][0-9]{4,})\s*:\s*1(?![0-9])', all_text, re.IGNORECASE)
        lfd_os_match = re.search(r'\b(?:Tizen|WebOS|Android|MagicInfo)\b', all_text, re.IGNORECASE)
        lfd_op_match = re.search(r'(?:16\s*[xX*/]\s*7|24\s*[xX*/]\s*7)', all_text, re.IGNORECASE)
        
        print("  LED Wall Specs:")
        print(f"    130 Inch:      {bool(size_match)}")
        print(f"    1.5 mm Pitch:  {bool(pitch_match)}")
        print(f"    1080p FHD Res: {bool(res_match)}")
        print(f"    SMD/COB Diode: {bool(diode_match)}")
        print(f"    >=5000:1 Cont: {bool(led_contrast_match)}")
        print(f"    >=3840Hz Refr: {bool(led_refresh_match)}")
        
        print("  LFD Specs:")
        print(f"    85 Inch:       {bool(lfd_size_match)}")
        print(f"    4K UHD Res:    {bool(lfd_res_match)}")
        print(f"    >=250 Nit Bri: {bool(lfd_brightness_match)}")
        print(f"    >=4700:1 Cont: {bool(lfd_contrast_match)}")
        print(f"    Tizen/WebOS:   {bool(lfd_os_match)}")
        print(f"    16x7 Operation:{bool(lfd_op_match)}")

if __name__ == "__main__":
    test()
