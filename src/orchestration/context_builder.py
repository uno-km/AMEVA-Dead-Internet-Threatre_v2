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


def build_emotion_prompt(bot_name: str, anger_targets: dict, effective_anger: float) -> str:
    """Compressed tag-based emotion prompt for 1.8B models"""
    try:
        if not isinstance(anger_targets, dict):
            anger_targets = {}

        safe_targets = {}
        for k, v in anger_targets.items():
            try:
                if not isinstance(k, str) or not k.strip():
                    continue
                num_val = float(v)
                if num_val < 0:
                    num_val = 0.0
                safe_targets[k] = num_val
            except Exception:
                continue

        try:
            effective_anger = float(effective_anger)
            if effective_anger < 0:
                effective_anger = 0.0
        except Exception:
            effective_anger = 0.0

        sorted_targets = sorted(
            safe_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        
        target_str = ",".join([f"{k}:{v:.0f}" for k, v in sorted_targets])
        if not target_str:
            target_str = "None"
            
        if effective_anger < 30:
            state = "CALM"
        elif effective_anger < 70:
            state = "IRRITATED"
        else:
            state = "ENRAGED"

        return f"[SYS_STATE: {bot_name}|ANG:{effective_anger:.0f}({state})|TGT:{target_str}]"

    except Exception as e:
        logger.warning(f"[EMOTION PROMPT WARNING] Failed to build emotion prompt for {bot_name}: {e}")
        return f"[SYS_STATE: {bot_name}|CALM]"


async def generate_director_directive(db, current_bot: str, recent_history: str, eff_anger: float) -> str:
    """
    Disabled God LLM call by default to save resources, 
    returns a short static directive instead.
    """
    directive = "Point out a specific flaw in the opponent's logic."
    
    try:
        bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
        if bot_state:
            bot_state.current_directive = directive
            db.commit()
    except Exception as e:
        logger.warning(f"[DB WARNING] Could not update directive for {current_bot}: {e}")
        
    return directive


def get_or_create_bot_state(db, current_bot):
    bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()

    if not bot_state:
        logger.warning(f"[TURN WARNING] BotState not found for {current_bot}. Creating fallback state.")
        bot_state = BotState(bot_name=current_bot, anger_targets="{}")
        db.add(bot_state)
        db.commit()
        db.refresh(bot_state)

    return bot_state


async def build_turn_context(db, post, current_bot, use_structured=False) -> Tuple[Dict, float, str, str]:
    bot_state = get_or_create_bot_state(db, current_bot)

    anger_dict = safe_json_loads(bot_state.anger_targets, {})
    if not isinstance(anger_dict, dict):
        anger_dict = {}

    safe_anger_dict = {}
    for k, v in anger_dict.items():
        try:
            safe_anger_dict[k] = float(v)
        except Exception:
            continue

    eff_anger = calculate_effective_anger(safe_anger_dict)
    emotion_directive = build_emotion_prompt(current_bot, safe_anger_dict, eff_anger)

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

    return safe_anger_dict, eff_anger, emotion_directive, recent_history
