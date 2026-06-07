"""
Prompt Adapter (Phase 2A)

Responsibilities:
1. build_structured_history(): Gist-based structured history (legacy + Phase 2)
2. build_prompt(): LPDE state → natural language prompt (Phase 2A, LPDE_FULL_PROMPT)

Key principle: NO raw vector dumps in prompts.
All LPDE state is decoded to natural language descriptions.
"""

import re
import logging
import asyncio
from typing import List, Optional

logger = logging.getLogger("PromptAdapter")

GIST_CACHE = {}  # maps (bot_name, raw_content) -> gist string
GIST_CACHE_LOCK = asyncio.Lock()


# =====================================================================
# Natural Language State Decoders
# =====================================================================

def _decode_arousal(arousal: float) -> str:
    if arousal > 0.7:
        return "You are highly agitated and emotionally charged."
    elif arousal > 0.3:
        return "You are noticeably irritated and tense."
    elif arousal > -0.3:
        return "You are relatively calm and collected."
    else:
        return "You are disengaged and apathetic about this discussion."


def _decode_valence(valence: float) -> str:
    if valence > 0.5:
        return "You feel positively about how this conversation is going."
    elif valence > 0.0:
        return "You feel somewhat neutral about the current exchange."
    elif valence > -0.5:
        return "You are mildly frustrated by the conversation."
    else:
        return "You feel deeply frustrated and negatively affected by this exchange."


def _decode_stance(stance: float) -> str:
    if stance > 0.5:
        return "You strongly support the main argument being discussed."
    elif stance > 0.1:
        return "You lean toward supporting the main argument."
    elif stance > -0.1:
        return "Your position is nuanced and flexible on this topic."
    elif stance > -0.5:
        return "You lean toward opposing the main argument."
    else:
        return "You firmly oppose the main argument."


def _decode_trust(trust: float, target: str) -> str:
    if trust > 0.5:
        return f"You have significant trust and respect for {target}."
    elif trust > 0.0:
        return f"You are cautiously open to what {target} says."
    elif trust > -0.5:
        return f"You are skeptical of {target}'s intentions and claims."
    else:
        return f"You deeply distrust {target} and doubt their sincerity."


def _decode_tension(tension: float, target: str) -> str:
    if tension > 0.7:
        return f"There is extreme tension between you and {target}."
    elif tension > 0.3:
        return f"You feel notable tension with {target}."
    elif tension > 0.1:
        return f"There is mild friction between you and {target}."
    else:
        return f"Your relationship with {target} is relatively calm."


def _decode_self_appraisal(self_appraisal: float) -> str:
    if self_appraisal > 0.5:
        return "You feel confident in your arguments and debating ability."
    elif self_appraisal > 0.0:
        return "You feel moderately sure of your position."
    elif self_appraisal > -0.5:
        return "You are starting to doubt some of your arguments."
    else:
        return "You feel uncertain and defensive about your position."


def _decode_influence(influence: float) -> str:
    if influence > 0.5:
        return "You feel like you are leading this debate."
    elif influence > 0.0:
        return "You feel like an active participant in this discussion."
    elif influence > -0.5:
        return "You feel somewhat sidelined in the conversation."
    else:
        return "You feel ignored and marginalized in this debate."


# =====================================================================
# Prompt Adapter Class
# =====================================================================

class PromptAdapter:
    """
    Adapts LPDE state and conversation history into LLM-ready prompts.
    Prevents script hallucination by structuring history as metadata.
    """
    def __init__(self):
        pass

    # -----------------------------------------------------------------
    # Gist Generation (for Structured History)
    # -----------------------------------------------------------------

    async def _generate_gist(self, bot_name: str, msg: str) -> str:
        """Generate a short stance summary via main LLM with heuristic fallback."""
        fallback = msg[:60].rstrip() + ("..." if len(msg) > 60 else "")
        try:
            from src.orchestration.runner import main_llm
            prompt = (
                f"Summarize this statement by {bot_name} into one short English phrase (5-10 words). "
                f"Output ONLY the summary phrase, nothing else.\n"
                f"Statement: \"{msg}\""
            )
            result = await main_llm.generate_completion(
                "You summarize forum comments into short stance descriptions.",
                prompt,
                max_tokens=30
            )
            gist = result.strip().strip('"\'')
            if gist and len(gist) > 3:
                return gist
        except Exception as e:
            logger.warning(f"Failed to generate gist via main_llm: {e}")
        return fallback

    # -----------------------------------------------------------------
    # Structured History Builder
    # -----------------------------------------------------------------

    async def build_structured_history(self, items: List[dict]) -> str:
        """
        Convert conversation items into structured stance-log format.
        items: [{"bot_name": ..., "message": ...}, ...]
        """
        if not items:
            return "No previous conversation."

        structured_lines = ["[Conversation History]"]
        for item in items:
            bot_name = item.get("bot_name", "Unknown")
            msg = item.get("message", "").strip()

            cache_key = (bot_name, msg)
            async with GIST_CACHE_LOCK:
                gist = GIST_CACHE.get(cache_key)

            if not gist:
                gist = await self._generate_gist(bot_name, msg)
                async with GIST_CACHE_LOCK:
                    GIST_CACHE[cache_key] = gist

            line = f"- {bot_name}'s stance: {gist}"
            structured_lines.append(line)

        return "\n".join(structured_lines)

    # -----------------------------------------------------------------
    # LPDE Full Prompt Builder (Phase 2A)
    # -----------------------------------------------------------------

    def build_prompt(
        self,
        current_bot: str,
        persona: str,
        lpde_state: dict,
        edge_summary: dict,
        target_bot: Optional[str],
        recent_history: str,
        post_content: str,
        claim_snippet: str = "",
        counter_arg_enabled: bool = False,
        god_directive: str = "",
    ) -> str:
        """
        Build the full LPDE-driven prompt for a crowd bot.

        Args:
            current_bot: The bot generating the reply (e.g. "bot_2")
            persona: The bot's persona system prompt
            lpde_state: {"affect": [v, a], "opinion": [s, g, m, ...], "power": [sa, si]}
            edge_summary: {target_bot: {"trust": ..., "tension": ..., ...}}
            target_bot: The primary debate opponent (from event extraction)
            recent_history: Formatted recent conversation string
            post_content: The original post content
            claim_snippet: Opponent's last claim (for counter-arg)
            counter_arg_enabled: Whether to enforce mandatory rebuttal
            god_directive: Optional director hint
        """
        sections = []

        # --- 1. Role Binding ---
        sections.append(
            f"You are {current_bot}. You are a real human internet user engaged in an online debate."
        )

        # --- 2. Persona (collapsed) ---
        if persona:
            # Strip the common rules suffix to keep it compact
            persona_short = persona.split("[STRICT COMPLIANCE RULES")[0].strip()
            if len(persona_short) > 200:
                persona_short = persona_short[:200].rstrip() + "..."
            sections.append(f"Personality:\n{persona_short}")

        # --- 3. Current Internal State (NL decoded) ---
        affect = lpde_state.get("affect", [0.0, 0.0])
        opinion = lpde_state.get("opinion", [0.0, 0.0, 0.0, 0.0])
        power = lpde_state.get("power", [0.0, 0.0])

        valence = affect[0] if len(affect) > 0 else 0.0
        arousal = affect[1] if len(affect) > 1 else 0.0
        stance = opinion[0] if len(opinion) > 0 else 0.0
        self_appraisal = power[0] if len(power) > 0 else 0.0
        influence = power[1] if len(power) > 1 else 0.0

        state_lines = [
            "Current Internal State:",
            f"- {_decode_arousal(arousal)}",
            f"- {_decode_valence(valence)}",
            f"- {_decode_stance(stance)}",
            f"- {_decode_self_appraisal(self_appraisal)}",
            f"- {_decode_influence(influence)}",
        ]

        # Edge-based relationship descriptions
        if target_bot and target_bot in edge_summary:
            edge = edge_summary[target_bot]
            trust = edge.get("trust", 0.0)
            tension = edge.get("tension", 0.0)
            state_lines.append(f"- {_decode_trust(trust, target_bot)}")
            state_lines.append(f"- {_decode_tension(tension, target_bot)}")

        sections.append("\n".join(state_lines))

        # --- 4. Post Content ---
        if post_content:
            post_short = post_content[:200].rstrip() + ("..." if len(post_content) > 200 else "")
            sections.append(f"Topic being debated:\n{post_short}")

        # --- 5. Recent History ---
        if recent_history and recent_history != "No previous conversation.":
            sections.append(f"Recent Conversation:\n{recent_history}")

        # --- 6. Counter-Argument Enforcement (Optional) ---
        if counter_arg_enabled and claim_snippet:
            sections.append(
                f"[MANDATORY REBUTTAL]\n"
                f"The opponent just claimed: \"{claim_snippet}\"\n"
                f"You MUST directly address this specific claim before stating your own position. "
                f"Do NOT ignore it. Either refute it with evidence, partially concede, or ask a pointed follow-up question."
            )

        # --- 7. Director Hint (Optional) ---
        if god_directive:
            sections.append(f"Director Hint: {god_directive}")

        # --- 8. Output Instructions ---
        other_bots = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        sections.append(
            f"Instruction:\n"
            f"Write a 1-sentence reply in English defending your stance. Address the last point directly.\n"
            f"Do NOT use prefixes like 'bot_x:'.\n"
            f"Mention exactly one of {', '.join(['@' + b for b in other_bots])} at the end of your message."
        )

        return "\n\n".join(sections)


prompt_adapter = PromptAdapter()
