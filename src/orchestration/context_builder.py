import json
import logging
import math
from typing import Dict, Tuple

from src.db.models import BotState, Comment

logger = logging.getLogger("ContextBuilder")

def safe_json_loads(value, default):
    try:
        if value is None:
            return default

        if isinstance(value, type(default)):
            return value

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default

        return default

    except Exception as e:
        logger.warning(f"[JSON WARNING] Failed to parse JSON value: {value} | Error: {e}")
        return default


def calculate_effective_anger(anger_dict: dict) -> float:
    if not anger_dict or not isinstance(anger_dict, dict):
        return 0.0

    sum_sq = 0.0
    for val in anger_dict.values():
        try:
            num = float(val)
            sum_sq += num ** 2
        except Exception:
            continue

    return math.sqrt(sum_sq)





async def build_turn_context(db, post, current_bot, target_bot=None) -> str:
    from src.orchestration.sanitizer import sanitize_generated_reply

    lines = []

    # 1. Opponent's First Comment
    target_first = None
    target_last = None
    if target_bot:
        target_comments = (
            db.query(Comment)
            .filter(Comment.post_id == post.id, Comment.bot_name == target_bot)
            .order_by(Comment.id.asc())
            .all()
        )
        if target_comments:
            target_first = target_comments[0]
            target_last = target_comments[-1]
            
            if target_first.content:
                msg = sanitize_generated_reply(target_first.content)
                if msg:
                    lines.append(f"Opponent's first comment ({target_bot}): {msg}")

    # 2. My Last Reply
    my_last = (
        db.query(Comment)
        .filter(Comment.post_id == post.id, Comment.bot_name == current_bot)
        .order_by(Comment.id.desc())
        .first()
    )
    if my_last and my_last.content:
        msg = sanitize_generated_reply(my_last.content)
        if msg:
            lines.append(f"What you said before (DO NOT REPEAT THIS): {msg}")

    # 3. Opponent's Latest Reply
    if target_last and target_last.content and (not target_first or target_last.id != target_first.id):
        msg = sanitize_generated_reply(target_last.content)
        if msg:
            lines.append(f"Opponent's latest reply ({target_bot}): {msg}")
    elif not target_bot:
        # Fallback if no specific target
        fallback_last = (
            db.query(Comment)
            .filter(Comment.post_id == post.id, Comment.bot_name != current_bot)
            .order_by(Comment.id.desc())
            .first()
        )
        if fallback_last and fallback_last.content:
            msg = sanitize_generated_reply(fallback_last.content)
            if msg:
                lines.append(f"Opponent's latest reply ({fallback_last.bot_name}): {msg}")

    recent_history = "\n\n".join(lines).strip()
    if len(recent_history) > 1000:
        recent_history = recent_history[-1000:]
        
    if not recent_history:
        recent_history = "No previous conversation."

    return recent_history
