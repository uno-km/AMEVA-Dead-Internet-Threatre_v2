import os
import sys
import unittest
import math

# DIT 경로를 sys.path에 삽입하여 app 패키지를 정상적으로 찾을 수 있게 함
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIT_PATH = os.path.join(BASE_DIR, "AMEVA-Dead-Internet-Theatre")
if DIT_PATH not in sys.path:
    sys.path.insert(0, DIT_PATH)

from src.core.personality_engine import PersonalityEngine

class TestPersonalityEngine(unittest.TestCase):
    def setUp(self):
        self.engine = PersonalityEngine()

    def test_clip_bounds(self):
        """Affect 등 상태 값이 무조건 [-1, 1] 바운드인지 검증"""
        self.assertEqual(self.engine._clip(1.5), 1.0)
        self.assertEqual(self.engine._clip(-1.5), -1.0)
        self.assertEqual(self.engine._clip(0.5), 0.5)

    def test_sigmoid_bound(self):
        """tanh 활성화 함수가 범위 안에 들어오는지 검증"""
        val = self.engine._sigmoid_bound(10.0)
        self.assertLessEqual(val, 1.0)
        self.assertGreaterEqual(val, 0.99)
        
        val_neg = self.engine._sigmoid_bound(-10.0)
        self.assertGreaterEqual(val_neg, -1.0)
        self.assertLessEqual(val_neg, -0.99)

if __name__ == '__main__':
    unittest.main()
