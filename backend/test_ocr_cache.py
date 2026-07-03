import os
import sys
import unittest
import tempfile
import time
import shutil
from unittest.mock import patch, MagicMock

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ocr_engine

class TestOcrCache(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        self.temp_cache_dir = os.path.join(self.test_dir, "temp_ocr_cache")
        
        # Override the OCR_CACHE_DIR in ocr_engine
        self.original_cache_dir = ocr_engine.OCR_CACHE_DIR
        ocr_engine.OCR_CACHE_DIR = self.temp_cache_dir
        os.makedirs(self.temp_cache_dir, exist_ok=True)

        # Patch heal_ocr_text to return the input text directly to avoid LLM requests in tests
        self.heal_patcher = patch('ocr_engine.heal_ocr_text', side_effect=lambda x: x)
        self.mock_heal = self.heal_patcher.start()

    def tearDown(self):
        # Stop patchers and restore cache dir and clean up temp files
        self.heal_patcher.stop()
        ocr_engine.OCR_CACHE_DIR = self.original_cache_dir
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cache_key_generation(self):
        # Create a dummy file
        dummy_file = os.path.join(self.test_dir, "dummy.txt")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("Hello World")
            
        key1 = ocr_engine._get_ocr_cache_key(dummy_file)
        self.assertTrue(len(key1) == 64)  # SHA256 hex length
        
        # Key should remain the same for unmodified file
        key2 = ocr_engine._get_ocr_cache_key(dummy_file)
        self.assertEqual(key1, key2)
        
        # Modify the file size/mtime
        time.sleep(0.1)  # Ensure time difference
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("Hello World Modified")
            
        key3 = ocr_engine._get_ocr_cache_key(dummy_file)
        self.assertNotEqual(key1, key3)

    @patch('fitz.open')
    @patch('ocr_engine._score_text_quality')
    def test_cache_hit_and_miss_digital_pdf(self, mock_score, mock_fitz_open):
        # Setup mock page and doc
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Verified digital PDF content. " * 10
        
        mock_doc = MagicMock()
        mock_doc.__len__.return_value = 1
        mock_doc.__getitem__.return_value = mock_page
        mock_doc.__enter__.return_value = mock_doc
        
        mock_fitz_open.return_value = mock_doc
        mock_score.return_value = 0.8
        
        dummy_pdf = os.path.join(self.test_dir, "test_doc.pdf")
        with open(dummy_pdf, "wb") as f:
            f.write(b"%PDF-1.4 dummy")
            
        # First extraction (Cache Miss)
        text1 = ocr_engine.extract_text_from_file(dummy_pdf)
        self.assertIn("Verified digital PDF content.", text1)
        self.assertEqual(mock_fitz_open.call_count, 1)
        
        # Reset mocks to see if we hit cache on second call
        mock_fitz_open.reset_mock()
        
        # Second extraction (Cache Hit)
        text2 = ocr_engine.extract_text_from_file(dummy_pdf)
        self.assertIn("Verified digital PDF content.", text2)
        
        # Ensure the PDF reader extraction was NOT called on cache hit
        mock_fitz_open.assert_not_called()

    @patch('ocr_engine.ocr_page')
    def test_cache_hit_and_miss_image(self, mock_ocr_page):
        # Create a dummy image
        from PIL import Image
        dummy_image_path = os.path.join(self.test_dir, "test_img.png")
        img = Image.new('RGB', (100, 100))
        img.save(dummy_image_path)
        
        mock_ocr_page.return_value = {
            "text": "Extracted text from image.",
            "confidence": 0.9,
            "quality": 0.8,
            "engine_used": "EasyOCR-CLAHE",
            "page": 1,
            "candidates": 1
        }
        
        # First call (Cache Miss)
        text1 = ocr_engine.extract_text_from_file(dummy_image_path)
        self.assertIn("Extracted text from image.", text1)
        self.assertEqual(mock_ocr_page.call_count, 1)
        
        # Reset mock
        mock_ocr_page.reset_mock()
        
        # Second call (Cache Hit)
        text2 = ocr_engine.extract_text_from_file(dummy_image_path)
        self.assertIn("Extracted text from image.", text2)
        mock_ocr_page.assert_not_called()

    def test_plain_text_caching(self):
        dummy_txt = os.path.join(self.test_dir, "test.txt")
        content = "Standard plain text content."
        with open(dummy_txt, "w", encoding="utf-8") as f:
            f.write(content)
            
        # First run (Read from file & write to cache)
        text1 = ocr_engine.extract_text_from_file(dummy_txt)
        self.assertEqual(text1, content)
        
        # Verify cache file exists
        key = ocr_engine._get_ocr_cache_key(dummy_txt)
        cache_file = os.path.join(self.temp_cache_dir, f"{key}.json")
        self.assertTrue(os.path.exists(cache_file))
        
        # Second run (Cache Hit)
        text2 = ocr_engine.extract_text_from_file(dummy_txt)
        self.assertEqual(text2, content)

if __name__ == '__main__':
    unittest.main()
