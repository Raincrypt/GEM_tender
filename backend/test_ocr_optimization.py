import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ocr_engine

class TestOcrOptimization(unittest.TestCase):

    @patch('ocr_engine.preprocess_clahe_color')
    @patch('ocr_engine._run_easy_ocr')
    @patch('ocr_engine._score_text_quality')
    @patch('ocr_engine.preprocess_deskew_sharpen')
    def test_strategy1_short_circuit(self, mock_prep_deskew, mock_score, mock_run_easy, mock_prep_clahe):
        # Setup: Strategy 1 meets both thresholds (conf=0.9, quality=0.8)
        mock_run_easy.return_value = ("High quality text output that meets all guidelines.", 0.9)
        mock_score.return_value = 0.8
        
        # Create a mock image
        img = Image.new('RGB', (100, 100))
        
        res = ocr_engine.ocr_page(img, page_num=1)
        
        # Assertions
        self.assertEqual(res["engine_used"], "EasyOCR-CLAHE")
        self.assertEqual(res["confidence"], 0.9)
        self.assertEqual(res["quality"], 0.8)
        self.assertEqual(res["candidates"], 1)
        
        # Verify that Strategy 1 was called, but Strategy 2 prep was NOT called
        mock_prep_clahe.assert_called_once()
        mock_prep_deskew.assert_not_called()

    @patch('ocr_engine.preprocess_clahe_color')
    @patch('ocr_engine.preprocess_deskew_sharpen')
    @patch('ocr_engine.preprocess_adaptive_binarize')
    @patch('ocr_engine._run_easy_ocr')
    @patch('ocr_engine._score_text_quality')
    def test_strategy2_short_circuit(self, mock_score, mock_run_easy, mock_prep_adaptive, mock_prep_deskew, mock_prep_clahe):
        # Setup: Strategy 1 fails threshold (conf=0.7, quality=0.5)
        # Strategy 2 meets threshold (conf=0.88, quality=0.75)
        mock_run_easy.side_effect = [
            ("Low quality text.", 0.7),
            ("High quality deskewed text output that is very clean.", 0.88)
        ]
        mock_score.side_effect = [0.5, 0.75]
        
        img = Image.new('RGB', (100, 100))
        
        res = ocr_engine.ocr_page(img, page_num=1)
        
        # Assertions
        self.assertEqual(res["engine_used"], "EasyOCR-Deskew")
        self.assertEqual(res["confidence"], 0.88)
        self.assertEqual(res["quality"], 0.75)
        self.assertEqual(res["candidates"], 2)
        
        # Verify Strategy 1 and 2 ran, but Strategy 3 prep (adaptive binarize) was NOT called
        mock_prep_clahe.assert_called_once()
        mock_prep_deskew.assert_called_once()
        mock_prep_adaptive.assert_not_called()

    @patch('ocr_engine.preprocess_clahe_color')
    @patch('ocr_engine.preprocess_deskew_sharpen')
    @patch('ocr_engine.preprocess_adaptive_binarize')
    @patch('ocr_engine.preprocess_otsu_binarize')
    @patch('ocr_engine.detect_table_cells')
    @patch('ocr_engine._run_easy_ocr')
    @patch('ocr_engine._run_tesseract')
    @patch('ocr_engine._score_text_quality')
    def test_no_short_circuit(self, mock_score, mock_tess, mock_easy, mock_detect, mock_otsu, mock_adaptive, mock_deskew, mock_clahe):
        # Setup: None meet early-exit thresholds
        mock_easy.return_value = ("Decent text.", 0.6)
        mock_tess.return_value = ("Decent text.", 0.6)
        mock_score.return_value = 0.5
        mock_detect.return_value = [] # no tables
        
        img = Image.new('RGB', (100, 100))
        
        res = ocr_engine.ocr_page(img, page_num=1)
        
        # Verify that all strategies were tried
        mock_clahe.assert_called_once()
        mock_deskew.assert_called_once()
        mock_adaptive.assert_called_once()
        mock_otsu.assert_called_once()
        mock_detect.assert_called_once()

if __name__ == '__main__':
    unittest.main()
