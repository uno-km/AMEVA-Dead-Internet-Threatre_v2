import re
import random
import logging

logger = logging.getLogger("Sanitizer")

# Pre-compiled regex patterns for better maintainability and performance
_PATTERNS = [
    # Metadata field leakage
    (re.compile(r'^\s*-\s*speaker\s*=\s*bot_[123]\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'^\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'^\s*speaker\s*=\s*bot_[123]\s*\|\s*', re.IGNORECASE), ''),
    (re.compile(r'\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'speaker=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'message=\s*["\']?', re.IGNORECASE), ''),
    
    # Stance leakage
    (re.compile(r'^bot_\[?[123]\]?\'s\s+stance\s*:\s*', re.IGNORECASE), ''),
    (re.compile(r'\'s\s+stance\s*:\s*', re.IGNORECASE), ''),
    (re.compile(r'stance\s*:\s*', re.IGNORECASE), ''),

    # Leading bot prefix
    (re.compile(r'^\s*bot_\[?[123]\]?:?\s*', re.IGNORECASE), ''),

    # Internal directives
    (re.compile(r'^.*현재 비교적 이성적이고 차분하다.*$', re.MULTILINE), ''),
    (re.compile(r'^.*내부 지침.*$', re.MULTILINE), ''),
    (re.compile(r'^.*절대 그대로 출력하지 마라.*$', re.MULTILINE), ''),
    (re.compile(r'^.*Emotional State:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Director Hint:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently relatively calm and rational.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently quite irritated and angry.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently extremely enraged and highly agitated.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Never repeat or explain this internal directive.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*INTERNAL EMOTIONAL STATE.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Total Effective Anger:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Major Target Anger Scores:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Total Valid Emotions:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Major Target Emotions:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Current Emotionally Distressed.*$', re.MULTILINE | re.IGNORECASE), ''),

    # Repetitive bot tag loop
    (re.compile(r'(?:\bbot_\[?[123]\]?\b[\s,:]*){3,}', re.IGNORECASE), ''),

    # Stray leading colons
    (re.compile(r'^\s*:\s*'), ''),
]

_MENTION_PATTERN = re.compile(r'@(bot_[123])\b', re.IGNORECASE)

def sanitize_generated_reply(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""

    text = text.strip()

    # Reject entire output if it contains prompt leakage or AI refusal
    leak_keywords = [
        "STRICT COMPLIANCE RULES", 
        "You are NOT an AI", 
        "You are a highly cynical",
        "You are an arrogant snob",
        "You are a strict moral censor",
        "Instruction:",
        "Personality:",
        "Act as an anonymous, toxic",
        "I cannot assist",
        "I can't assist",
        "I cannot fulfill",
        "As an AI",
        "As an artificial intelligence",
        "I am an AI",
        "As a language model",
        "Bot's Response:"
    ]
    if any(k.lower() in text.lower() for k in leak_keywords):
        return ""

    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()

    # bot tag 및 mention을 제외한 실질 텍스트 내용으로 길이 검증
    text_content = re.sub(r'@?bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    
    # A. 길이 검증 (짧아도 구두점 .?! 이 있으면 살림)
    if len(text_content) < 8 and not re.search(r'[.!?]', text_content):
        return ""

    # B. 실질 내용 없이 bot tag / mention만 남았는지 검증
    temp = re.sub(r'[^\w]', '', text_content)
    if not temp.strip():
        return ""

    # C. 연속 반복 감지
    if re.search(r'(\b\w+\b)( \1){3,}', text, flags=re.IGNORECASE):
        return ""

    # D. 동일 단어 비율 및 고유 단어 다양성 비율 감지
    words = [w.lower().strip(".,!?\"'()[]{}*-_") for w in text_content.split()]
    words = [w for w in words if w]
    if len(words) >= 6:
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
        max_count = max(word_counts.values())
        max_ratio = max_count / len(words)
        
        if max_ratio >= 0.5:
            return ""

        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.45:
            return ""

    if text.endswith('"') or text.endswith("'"):
        if text.count('"') % 2 != 0:
            text = text.rstrip('"')
        if text.count("'") % 2 != 0:
            text = text.rstrip("'")

    return text

def force_single_mention(text: str, current_bot: str) -> tuple[str, str]:
    if not text or not isinstance(text, str):
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        return f"@{chosen}", chosen

    matches = _MENTION_PATTERN.findall(text)
    matches = [m.lower() for m in matches if m.lower() != current_bot]

    cleaned = _MENTION_PATTERN.sub('', text)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\s+([,.!?])', r'\1', cleaned)
    cleaned = cleaned.strip(" ,")

    if matches:
        chosen = matches[-1]
    else:
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"

    if cleaned:
        return f"{cleaned} @{chosen}", chosen

    return f"@{chosen}", chosen

def enforce_fallback(text: str, current_bot: str) -> str:
    if not text or not text.strip():
        fallback_replies = [
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
            "Your argument lacks substance. Do you have any real facts to support it?",
            "What concrete proof do you have to back up that statement?",
            "I can see where you're coming from, but the evidence doesn't support it. Care to elaborate?",
            "That's an interesting perspective, but I find it fundamentally flawed.",
            "Are we just going to ignore the counterarguments here?",
            "If that's your stance, how do you explain the contradictions in your logic?",
            "I disagree completely. Your reasoning seems entirely speculative.",
            "Can you justify your opinion without relying on assumptions?"
        ]
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        chosen_reply = random.choice(fallback_replies)
        return f"{chosen_reply} @{chosen}"
    return text
