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





async def build_turn_context(db, post, current_bot, use_structured=False) -> str:
    # 1A legacy features removed: safe_anger_dict, eff_anger, emotion_directive

    from src.orchestration.sanitizer import sanitize_generated_reply

    recent_c = (
        db.query(Comment)
        .filter(Comment.post_id == post.id)
        .order_by(Comment.id.desc())
        .limit(3)
        .all()
    )

    async def _format_recent_history(items):
        valid_items = []
        for item in reversed(items):
            if not item or not item.content:
                continue
            msg = sanitize_generated_reply(item.content)
            if not msg:
                continue
            valid_items.append({"bot_name": item.bot_name, "message": msg})

        if use_structured:
            from src.core.prompt_adapter import prompt_adapter
            return await prompt_adapter.build_structured_history(valid_items)
        else:
            lines = []
            for item in valid_items:
                lines.append(f"{item['bot_name']}: {item['message']}")
            return "\n".join(lines).strip()

    recent_history = await _format_recent_history(recent_c)

    if len(recent_history) > 600:
        recent_history = recent_history[-600:]

    return recent_history
