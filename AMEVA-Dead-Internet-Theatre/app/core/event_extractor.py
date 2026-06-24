"""
Event Extractor (Phase 2A)

Deterministic, rule-based event extraction from bot utterances.
NO LLM calls — purely regex + keyword matching.

Events:
  MENTION   - @bot_x direct call
  AGREE     - agreement keywords
  DISAGREE  - disagreement keywords
  ATTACK    - personal/emotional attacks
  QUESTION  - evidence demands / questions
  CONCEDE   - partial concession
  IGNORE    - no mention, self-focused monologue

Target inference priority:
  1. @bot_x present → that bot
  2. No mention → last_target (previous commenter)
  3. Neither → None
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("EventExtractor")

# --- Keyword pools (case-insensitive matching) ---

_AGREE_KEYWORDS = [
    r"\bi agree\b", r"\byou'?re right\b", r"\bgood point\b", r"\bexactly\b",
    r"\bwell said\b", r"\bthat'?s true\b", r"\babsolutely\b", r"\bcorrect\b",
    r"\bfair point\b", r"\byou make a good\b", r"\bi support\b",
    r"\bi concur\b", r"\bspot on\b", r"\bthat'?s fair\b",
    r"\bi agree with you\b", r"\bmakes sense\b", r"\bi can see that\b",
    r"\bvalid point\b", r"\bso true\b", r"\bi am with you\b", r"\b100%\b",
    r"\byeah\b", r"\byes\b", r"\bof course\b", r"\bindeed\b"
]

_DISAGREE_KEYWORDS = [
    r"\bi disagree\b", r"\bthat'?s wrong\b", r"\bnonsense\b", r"\bridiculous\b",
    r"\bthat'?s not true\b", r"\byou'?re wrong\b", r"\babsurd\b",
    r"\bmisguided\b", r"\bflawed\b", r"\bmisleading\b", r"\bfalse\b",
    r"\bcompletely wrong\b", r"\bmake no sense\b",
    r"\bthat doesn'?t hold\b", r"\bthat'?s a stretch\b",
    r"\bi don'?t think so\b", r"\byou are missing\b", r"\bbullshit\b",
    r"\bthat'?s false\b", r"\byou'?re ignoring\b", r"\bnot exactly\b",
    r"\bhard to believe\b", r"\bno way\b", r"\bdisagree with\b", r"\bwrong about\b"
]

_ATTACK_KEYWORDS = [
    r"\bidiot\b", r"\bshut up\b", r"\bpathetic\b", r"\bignorant\b",
    r"\bstupid\b", r"\bmoron\b", r"\bclueless\b", r"\bjoke\b",
    r"\bclown\b", r"\bdumb\b", r"\bfool\b", r"\bworthless\b",
    r"\btrash\b", r"\bgarbage\b", r"\bdisgust\b", r"\bdelusional\b",
    r"\bhypocrite\b", r"\bliar\b", r"\bskill issue\b", r"\bcry about it\b",
    r"\bwho asked\b",
]

_QUESTION_KEYWORDS = [
    r"\bexplain\b", r"\bprove\b", r"\bevidence\b", r"\bsource\b",
    r"\bwhy do you\b", r"\bhow do you\b", r"\bwhat evidence\b",
    r"\bcan you show\b", r"\bback.{0,5}up\b", r"\bjustif\w*\b",
    r"\bwhat makes you\b", r"\bwhere'?s your\b",
    r"\bwhat about\b", r"\bcare to explain\b", r"\bdo you really\b",
    r"\bare you sure\b", r"\bhow can you\b", r"\bwhere is the\b",
    r"\bwhat if\b"
]

_CONCEDE_KEYWORDS = [
    r"\bi admit\b", r"\bfair enough\b", r"\byou have a point\b",
    r"\bi was wrong\b", r"\bi'?ll give you that\b", r"\bpartially agree\b",
    r"\bi see your point\b", r"\bthat'?s a valid\b", r"\bi concede\b",
    r"\bi acknowledge\b", r"\bi stand corrected\b", r"\bi guess you'?re right\b",
    r"\bperhaps you'?re right\b", r"\bmaybe you'?re right\b", r"\bthat might be true\b"
]


def _match_any(text: str, patterns: list[str]) -> bool:
    """Check if any regex pattern matches in text (case-insensitive)."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _extract_mention_target(text: str, speaker: str, all_bots: list[str]) -> Optional[str]:
    """Extract the @mention target bot, excluding self-mentions."""
    matches = re.findall(r'@(bot_[123])\b', text, re.IGNORECASE)
    normalized = [m.lower() for m in matches]
    # Exclude self-mentions
    others = [m for m in normalized if m != speaker and m in all_bots]
    return others[-1] if others else None


def _compute_intensity(events: list[str]) -> float:
    """Compute 0-1 intensity score based on event types."""
    base = 0.1
    if "ATTACK" in events:
        base = max(base, 0.8)
    if "DISAGREE" in events:
        base = max(base, 0.5)
    if "QUESTION" in events:
        base = max(base, 0.4)
    if "AGREE" in events:
        base = min(base, 0.2)
    if "CONCEDE" in events:
        base = min(base, 0.15)
    return min(1.0, max(0.0, base))


def _extract_claim_snippet(
    parent_comment_text: Optional[str],
    max_len: int = 120
) -> str:
    """Extract a short claim snippet from the parent comment for counter-arg use."""
    if not parent_comment_text or not isinstance(parent_comment_text, str):
        return ""
    text = parent_comment_text.strip()
    # Remove @mentions from the snippet
    text = re.sub(r'@bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    # Try to cut at sentence boundary
    truncated = text[:max_len]
    last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_period > max_len // 2:
        return truncated[:last_period + 1]
    return truncated.rstrip() + "..."


def extract_events(
    comment_text: str,
    speaker: str,
    all_bots: list[str],
    parent_comment_text: Optional[str] = None,
    last_target: Optional[str] = None
) -> dict:
    """
    Extract structured events from a bot's comment text.

    Args:
        comment_text: The current bot's reply text
        speaker: Bot name of the current speaker (e.g. "bot_1")
        all_bots: List of all bot names (e.g. ["bot_1", "bot_2", "bot_3"])
        parent_comment_text: Text of the previous comment (for claim_snippet)
        last_target: Bot name of the previous speaker (fallback target)

    Returns:
        {
            "speaker": str,
            "target": str | None,
            "events": list[str],
            "intensity": float,        # 0~1
            "claim_snippet": str,       # opponent's claim for counter-arg
        }
    """
    if not comment_text or not isinstance(comment_text, str):
        return {
            "speaker": speaker,
            "target": None,
            "events": [],
            "intensity": 0.0,
            "claim_snippet": "",
        }

    text = comment_text.strip()
    events = []

    # 1. MENTION detection
    mention_target = _extract_mention_target(text, speaker, all_bots)
    if mention_target:
        events.append("MENTION")

    # 2. Semantic event detection (keyword-based)
    if _match_any(text, _AGREE_KEYWORDS):
        events.append("AGREE")
    if _match_any(text, _DISAGREE_KEYWORDS):
        events.append("DISAGREE")
    if _match_any(text, _ATTACK_KEYWORDS):
        events.append("ATTACK")
    # Question: also check for trailing '?'
    if _match_any(text, _QUESTION_KEYWORDS) or text.rstrip().endswith("?"):
        events.append("QUESTION")
    if _match_any(text, _CONCEDE_KEYWORDS):
        events.append("CONCEDE")

    # 3. IGNORE detection: no mention AND no engagement keywords
    if not mention_target and not any(
        e in events for e in ["AGREE", "DISAGREE", "ATTACK", "QUESTION", "CONCEDE"]
    ):
        if len(text) < 40:
            events.append("IGNORE")
        else:
            # Fallback to mild disagreement if engaged but lacking keywords
            events.append("DISAGREE")

    # 4. Target inference priority:
    #    @bot_x > last commenter > None
    target = mention_target
    if target is None:
        target = last_target if last_target and last_target != speaker else None

    # 5. Intensity
    intensity = _compute_intensity(events)

    # 6. Claim snippet from parent comment
    claim_snippet = _extract_claim_snippet(parent_comment_text)

    result = {
        "speaker": speaker,
        "target": target,
        "events": events,
        "intensity": intensity,
        "claim_snippet": claim_snippet,
    }

    logger.info(f"[EVENT] {speaker} → {target}: {events} (intensity={intensity:.2f})")
    return result
