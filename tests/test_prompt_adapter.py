import os
import sys
import unittest

# DIT 경로를 sys.path에 삽입하여 app 패키지를 정상적으로 찾을 수 있게 함
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIT_PATH = os.path.join(BASE_DIR, "AMEVA-Dead-Internet-Theatre")
if DIT_PATH not in sys.path:
    sys.path.insert(0, DIT_PATH)

from src.core.prompt_adapter import PromptAdapter

class TestPromptAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.adapter = PromptAdapter()

    async def test_build_structured_history(self):
        """Verify that the structured history avoids script/dialogue layout by using stances"""
        items = [
            {"bot_name": "bot_1", "message": "I disagree."},
            {"bot_name": "bot_2", "message": "Why?"}
        ]
        history = await self.adapter.build_structured_history(items, None)
        
        self.assertIn("[Conversation History]", history)
        self.assertIn("- bot_1's stance:", history)
        self.assertIn("- bot_2's stance:", history)
        
        # Verify no script colon format is present
        self.assertNotIn("\nbot_1:", history)

    async def test_empty_history(self):
        self.assertEqual(await self.adapter.build_structured_history([], None), "No previous conversation.")

if __name__ == '__main__':
    unittest.main()
