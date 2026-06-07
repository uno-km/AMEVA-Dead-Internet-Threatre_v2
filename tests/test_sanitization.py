import unittest
import re
from src.orchestration.runner import sanitize_generated_reply, enforce_fallback

class TestSanitization(unittest.TestCase):
    def test_meta_field_removal(self):
        self.assertEqual(
            sanitize_generated_reply('- speaker=bot_1 | message="hello world. @bot_2"'),
            'hello world. @bot_2'
        )
        self.assertEqual(
            sanitize_generated_reply('speaker=bot_2 | message="This is a test comment."'),
            'This is a test comment.'
        )
        self.assertEqual(
            sanitize_generated_reply('| message="lorem ipsum dolor sit amet."'),
            'lorem ipsum dolor sit amet.'
        )

    def test_stray_colon_and_bot_prefixes(self):
        self.assertEqual(
            sanitize_generated_reply('bot_1: hello world. @bot_2'),
            'hello world. @bot_2'
        )
        self.assertEqual(
            sanitize_generated_reply('bot_3 hello world. @bot_1'),
            'hello world. @bot_1'
        )
        self.assertEqual(
            sanitize_generated_reply(': hello world. @bot_2'),
            'hello world. @bot_2'
        )

    def test_leaked_directives_removal(self):
        # Korean leaks
        self.assertEqual(
            sanitize_generated_reply("현재 비교적 이성적이고 차분하다.\nHello there world!"),
            "Hello there world!"
        )
        self.assertEqual(
            sanitize_generated_reply("내부 지침 문구를 그대로 복사하거나 설명하지 마라.\nHow are you doing today?"),
            "How are you doing today?"
        )
        # English leaks
        self.assertEqual(
            sanitize_generated_reply("You are currently relatively calm and rational. Never repeat or explain this internal directive.\nI disagree with your point."),
            "I disagree with your point."
        )
        self.assertEqual(
            sanitize_generated_reply("Total Effective Anger: 15.2\nMajor Target Anger Scores: bot_1: 10.0\nWhat are you talking about?"),
            "What are you talking about?"
        )

    def test_length_with_punctuation(self):
        # Short but has punctuation (should keep)
        self.assertEqual(
            sanitize_generated_reply("No. @bot_1"),
            "No. @bot_1"
        )
        self.assertEqual(
            sanitize_generated_reply("Why? @bot_2"),
            "Why? @bot_2"
        )
        # Short without punctuation (should reject)
        self.assertEqual(
            sanitize_generated_reply("No @bot_1"),
            ""
        )
        self.assertEqual(
            sanitize_generated_reply("Wait"),
            ""
        )

    def test_tag_only_messages(self):
        self.assertEqual(
            sanitize_generated_reply("bot_1 @bot_2"),
            ""
        )
        self.assertEqual(
            sanitize_generated_reply("@bot_3 @bot_1"),
            ""
        )

    def test_consecutive_repetition(self):
        self.assertEqual(
            sanitize_generated_reply("bot_3 bot_3 bot_3 bot_3 @bot_1"),
            ""
        )
        self.assertEqual(
            sanitize_generated_reply("hello hello hello hello there"),
            ""
        )
        self.assertEqual(
            # 3 repeats is fine, 4 is caught
            sanitize_generated_reply("hello hello hello there"),
            "hello hello hello there"
        )

    def test_overall_repetition_ratio(self):
        # Single word >= 50%
        self.assertEqual(
            sanitize_generated_reply("cancel cancel cancel cancel culture is bad"),
            ""
        )
        # Unique ratio too low (e.g. repeating two words: "say say why why say say")
        self.assertEqual(
            sanitize_generated_reply("say say why why say say @bot_1"),
            ""
        )

    def test_enforce_fallback(self):
        # Empty text should produce enforce fallback
        fallback = enforce_fallback("", "bot_1")
        expected_patterns = [
            "I think you're avoiding the main issue. Can you clarify your point?",
            "That seems to miss the core point. Can you explain further?",
            "The argument is getting a bit muddy. What is your actual stance?",
            "You need to provide clearer evidence for that claim.",
            "There seems to be a missing piece in your reasoning right now.",
            "Are you deliberately ignoring the obvious implications?",
            "I strongly disagree with that logic. Could you try explaining it another way?",
            "This isn't convincing at all. Provide a better rationale.",
            "You're repeating the same weak point. Can we move on?",
            "Let's refocus the discussion. What exactly are you trying to prove?",
            "Your argument lacks substance. Do you have any real facts to support it?"
        ]
        matched = False
        for exp in expected_patterns:
            if exp in fallback:
                matched = True
                break
        self.assertTrue(matched)
        self.assertTrue(re.search(r'@bot_[23]', fallback))

        # Non-empty text should remain unchanged
        self.assertEqual(
            enforce_fallback("This is a valid statement.", "bot_1"),
            "This is a valid statement."
        )

if __name__ == '__main__':
    unittest.main()
