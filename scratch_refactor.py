import re
import sys

with open(r'c:\ameva\AMEVA-Dead-Internet-Threatre\src\orchestration\runner.py', 'r', encoding='utf-8') as f:
    code = f.read()

imports_to_add = """
from src.orchestration.sanitizer import sanitize_generated_reply, force_single_mention, enforce_fallback
from src.orchestration.context_builder import (
    safe_json_loads, calculate_effective_anger, build_emotion_prompt,
    generate_director_directive, get_or_create_bot_state, build_turn_context
)
"""

if "from src.orchestration.sanitizer" not in code:
    code = code.replace("from src.core.personality_engine import personality_engine", "from src.core.personality_engine import personality_engine" + imports_to_add)

# Delete functions using regex
functions_to_delete = [
    r'def safe_json_loads\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def calculate_effective_anger\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def build_emotion_prompt\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'async def generate_director_directive\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def get_or_create_bot_state\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'async def build_turn_context\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def force_single_mention\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def enforce_fallback\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
    r'def sanitize_generated_reply\(.*?:\n(?:    .*\n)*?(?=\n\S|$)',
]

for pattern in functions_to_delete:
    code = re.sub(pattern, '', code, flags=re.MULTILINE)

# Also fix the `generate_relay_reply` `last_target`
code = code.replace(
    "last_target=None,",
    "last_target=last_speaker,"
)

# And fix the intervention trigger from `arousal_val > 0.7` to `tension > 0.6`
code = code.replace(
    "arousal_val = lpde_state.get(\"affect\", [0.0, 0.0])[1]",
    "arousal_val = lpde_state.get(\"affect\", [0.0, 0.0])[1]\n            tension_val = personality_engine.get_edges_for_bot(db, post.session_id, current_bot).get('tension', 0.0)"
)
code = code.replace(
    "should_intervene = (turn_idx % 3 == 0 and turn_idx > 0) or arousal_val > 0.7",
    "should_intervene = (turn_idx % 3 == 0 and turn_idx > 0) or tension_val > 0.6"
)


# generate_director_directive has one less argument now in runner.py
code = code.replace(
    "god_directive = await generate_director_directive(db, current_bot, recent_history, eff_anger)",
    "god_directive = await generate_director_directive(db, current_bot, recent_history, eff_anger)"
)

with open(r'c:\ameva\AMEVA-Dead-Internet-Threatre\src\orchestration\runner.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Refactored runner.py successfully!")
