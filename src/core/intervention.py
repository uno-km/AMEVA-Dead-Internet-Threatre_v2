"""
Intervention Engine (Phase 2B)

God LLM acts as a Latent Vector Intervention Controller.
Instead of text directives, it generates JSON deltas that perturb agent state-space.

Intervention kinds:
  stir      - Escalate debate tension (Arousal +, Attention +)
  cool      - De-escalate (Arousal -, Tension -)
  redirect  - Shift attention target
  reconcile - Promote trust and de-tension

Safety guards:
  - Malformed JSON → no-op
  - Delta dimension mismatch → no-op
  - Each value clamped to ±0.5
  - All attempts logged to InterventionLog
"""

import json
import re
import logging
from typing import Optional
from sqlalchemy.orm import Session

from src.db.models import InterventionLog, CurrentAgentState

logger = logging.getLogger("Intervention")

# Maximum absolute delta value per intervention
MAX_DELTA = 0.5

# Valid intervention kinds
VALID_KINDS = {"stir", "cool", "redirect", "reconcile"}

# Dimension names for validation
VALID_DIMS = {"affect", "opinion", "power"}
DIM_SIZES = {"affect": 2, "opinion": 4, "power": 2}


def _clamp(val: float, lo: float = -MAX_DELTA, hi: float = MAX_DELTA) -> float:
    return max(lo, min(hi, val))


async def generate_intervention_json(
    god_llm,
    bot_name: str,
    current_state: dict,
    recent_history: str,
    arousal: float,
) -> Optional[dict]:
    """
    Ask God LLM to produce a JSON intervention delta.
    Returns parsed dict or None on failure.
    """
    prompt = (
        f"[Debate Director Intervention]\n"
        f"Target bot: {bot_name}\n"
        f"Current arousal level: {arousal:.2f} (scale: -1 to 1)\n"
        f"Recent conversation:\n{recent_history[:400] if recent_history else 'None'}\n\n"
        f"You are the debate director. Decide whether to intervene.\n"
        f"If no intervention is needed, output: {{\"kind\": \"none\"}}\n"
        f"If intervention is needed, output ONE of:\n"
        f"- {{\"kind\": \"stir\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.0, 0.3]}}, \"reason\": \"increase tension\"}}\n"
        f"- {{\"kind\": \"cool\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.0, -0.3]}}, \"reason\": \"reduce escalation\"}}\n"
        f"- {{\"kind\": \"reconcile\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.1, -0.2]}}, \"reason\": \"promote de-escalation\"}}\n"
        f"Output ONLY valid JSON, no other text."
    )

    try:
        result = await god_llm.generate_completion(
            "You are a debate director that outputs JSON intervention commands.",
            prompt,
            max_tokens=120,
        )
        return parse_intervention_json(result)
    except Exception as e:
        logger.warning(f"[INTERVENTION] Failed to generate intervention for {bot_name}: {e}")
        return None


def parse_intervention_json(raw: str) -> Optional[dict]:
    """
    Parse and validate a God LLM intervention response.
    Returns validated dict or None.
    """
    if not raw or not isinstance(raw, str):
        return None

    raw = raw.strip()

    # Extract JSON from potential markdown wrappers
    md_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if md_match:
        raw = md_match.group(1).strip()

    # Find JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning(f"[INTERVENTION] No JSON found in: {raw[:100]}")
        return None

    json_str = raw[start:end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"[INTERVENTION] JSON parse failed: {e}")
        return None

    if not isinstance(data, dict):
        return None

    kind = data.get("kind", "").lower().strip()

    # "none" means no intervention
    if kind == "none":
        return None

    # Validate kind
    if kind not in VALID_KINDS:
        logger.warning(f"[INTERVENTION] Unknown kind: {kind}")
        return None

    # Validate and clamp delta
    delta = data.get("delta", {})
    if not isinstance(delta, dict):
        delta = {}

    clamped_delta = {}
    for dim_name, values in delta.items():
        if dim_name not in VALID_DIMS:
            continue
        if not isinstance(values, list):
            continue
        expected_len = DIM_SIZES.get(dim_name, 0)
        if len(values) != expected_len:
            logger.warning(
                f"[INTERVENTION] Dimension mismatch for {dim_name}: "
                f"expected {expected_len}, got {len(values)}. Skipping."
            )
            continue
        clamped_delta[dim_name] = [_clamp(float(v)) for v in values]

    return {
        "kind": kind,
        "target_bot": data.get("target_bot", ""),
        "delta": clamped_delta,
        "reason": str(data.get("reason", ""))[:200],
    }


def apply_intervention(
    db: Session,
    session_id: int,
    turn_index: int,
    intervention: dict,
) -> bool:
    """
    Apply an intervention delta to the target bot's state.
    Logs to InterventionLog regardless of success.
    Returns True if delta was applied.
    """
    target_bot = intervention.get("target_bot", "")
    kind = intervention.get("kind", "")
    delta = intervention.get("delta", {})
    reason = intervention.get("reason", "")

    # Log the intervention attempt
    log_entry = InterventionLog(
        session_id=session_id,
        turn_index=turn_index,
        target_bot=target_bot,
        kind=kind,
        delta_json=json.dumps(delta, ensure_ascii=False),
        reason=reason,
    )
    db.add(log_entry)

    if not delta or not target_bot:
        logger.info(f"[INTERVENTION] Logged {kind} for {target_bot} (no delta to apply)")
        return False

    # Load target agent state
    agent = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == session_id,
        CurrentAgentState.bot_name == target_bot,
    ).first()

    if not agent:
        logger.warning(f"[INTERVENTION] Agent state not found for {target_bot}")
        return False

    # Apply deltas
    applied = False
    for dim_name, delta_values in delta.items():
        json_field = f"{dim_name}_json"
        current_raw = getattr(agent, json_field, None)
        if current_raw is None:
            continue

        try:
            current_values = json.loads(current_raw)
        except Exception:
            continue

        if not isinstance(current_values, list) or len(current_values) != len(delta_values):
            continue

        new_values = []
        for cur, dv in zip(current_values, delta_values):
            # Apply delta and clip to [-1, 1]
            new_val = max(-1.0, min(1.0, float(cur) + float(dv)))
            new_values.append(round(new_val, 4))

        setattr(agent, json_field, json.dumps(new_values))
        applied = True

    if applied:
        logger.info(
            f"[INTERVENTION] Applied {kind} to {target_bot}: delta={delta} reason={reason}"
        )
    else:
        logger.warning(f"[INTERVENTION] No delta applied for {kind} on {target_bot}")

    return applied
