"""
Stance Role System (Phase 3)

각 봇의 '입장 구조(stance role)'를 정의하고 세션 시작 시 배정한다.
정치 라벨이 아닌 추상화된 역할(role)로 설계되어 있음.

Role 구조:
  role_label:     사람이 읽기 쉬운 역할 이름
  stance_pole:    논쟁 축 방향 [-1.0 ~ +1.0] (opinion[0]에 매핑)
  conviction:     자기 입장 확신도 [0.0 ~ 1.0] (opinion[1]에 매핑)
  flexibility:    반박 시 흔들림 정도 [0.0 ~ 1.0] (opinion[3]에 매핑)
  opportunism:    강한 쪽에 붙는 경향 [0.0 ~ 1.0] (role_meta_json에 저장)
  aggression_bias:공격적 반응 경향 [0.0 ~ 1.0] (role_meta_json에 저장)

배정 규칙 (assign_initial_role_triplet):
  - 기본: pole_a_hardliner + pole_b_hardliner + third_role
  - third_role: swing_moderate / lean_a_soft / lean_b_soft /
                opportunistic_bandwagon / nihilist_observer 중 랜덤
  - 양극단 2명은 항상 고정, 3번째만 변동
  - 절대 금지: 셋 다 같은 pole / 셋 다 neutral / 셋 다 high flexibility
"""

import random
import logging
from typing import Optional

logger = logging.getLogger("StanceRoles")

# =====================================================================
# Role Preset Definitions
# =====================================================================

ROLE_PRESETS: dict[str, dict] = {
    "pole_a_hardliner": {
        "role_label": "pole_a_hardliner",
        "stance_pole": -0.9,
        "conviction": 0.9,
        "flexibility": 0.1,
        "opportunism": 0.1,
        "aggression_bias": 0.7,
    },
    "pole_b_hardliner": {
        "role_label": "pole_b_hardliner",
        "stance_pole": 0.9,
        "conviction": 0.9,
        "flexibility": 0.1,
        "opportunism": 0.1,
        "aggression_bias": 0.7,
    },
    "swing_moderate": {
        "role_label": "swing_moderate",
        "stance_pole": 0.0,
        "conviction": 0.4,
        "flexibility": 0.85,
        "opportunism": 0.45,
        "aggression_bias": 0.25,
    },
    "lean_a_soft": {
        "role_label": "lean_a_soft",
        "stance_pole": -0.35,
        "conviction": 0.55,
        "flexibility": 0.55,
        "opportunism": 0.25,
        "aggression_bias": 0.35,
    },
    "lean_b_soft": {
        "role_label": "lean_b_soft",
        "stance_pole": 0.35,
        "conviction": 0.55,
        "flexibility": 0.55,
        "opportunism": 0.25,
        "aggression_bias": 0.35,
    },
    "opportunistic_bandwagon": {
        "role_label": "opportunistic_bandwagon",
        "stance_pole": 0.1,
        "conviction": 0.3,
        "flexibility": 0.7,
        "opportunism": 0.9,
        "aggression_bias": 0.45,
    },
    "nihilist_observer": {
        "role_label": "nihilist_observer",
        "stance_pole": 0.0,
        "conviction": 0.5,
        "flexibility": 0.3,
        "opportunism": 0.2,
        "aggression_bias": 0.5,
    },
}

# 3번째 봇에 배정 가능한 역할 목록 (양극단 제외)
_THIRD_ROLE_POOL = [
    "swing_moderate",
    "lean_a_soft",
    "lean_b_soft",
    "opportunistic_bandwagon",
    "nihilist_observer",
]


def get_role_profile(role_label: str) -> dict:
    """
    role_label로 preset dict를 반환.
    없으면 swing_moderate를 기본값으로 반환.
    """
    profile = ROLE_PRESETS.get(role_label)
    if profile is None:
        logger.warning(f"[STANCE] Unknown role_label '{role_label}'. Defaulting to swing_moderate.")
        return ROLE_PRESETS["swing_moderate"].copy()
    return profile.copy()


def assign_initial_role_triplet(seed: Optional[int] = None) -> dict[str, dict]:
    """
    세션 시작 시 3개 봇에 역할을 배정한다.

    배정 규칙:
      - pole_a_hardliner + pole_b_hardliner는 항상 배정
      - 3번째 봇은 _THIRD_ROLE_POOL에서 랜덤 선택
      - 세 봇의 순서는 무작위로 섞음 (어떤 봇이 hardliner가 될지 랜덤)
      
    Returns:
      {
        "bot_1": {...role profile...},
        "bot_2": {...role profile...},
        "bot_3": {...role profile...}
      }
    """
    if seed is not None:
        random.seed(seed)

    bots = ["bot_1", "bot_2", "bot_3"]

    # 양극단 2명은 고정, 3번째 역할만 랜덤
    third_role_label = random.choice(_THIRD_ROLE_POOL)

    role_labels = [
        "pole_a_hardliner",
        "pole_b_hardliner",
        third_role_label,
    ]

    # 3봇에 역할을 랜덤으로 섞어 배정
    random.shuffle(role_labels)

    triplet = {}
    for bot_name, role_label in zip(bots, role_labels):
        triplet[bot_name] = get_role_profile(role_label)
        logger.info(f"[STANCE_INIT] {bot_name} -> {role_label}")

    return triplet


def decode_role_orientation(role_profile: dict) -> str:
    """
    role_profile을 프롬프트에 삽입할 자연어 텍스트로 디코딩.
    prompt_adapter.py에서 호출된다.
    """
    label = role_profile.get("role_label", "swing_moderate")
    conviction = role_profile.get("conviction", 0.5)
    flexibility = role_profile.get("flexibility", 0.5)
    opportunism = role_profile.get("opportunism", 0.3)

    lines = ["Role Orientation:"]

    # 1. Pole description
    if label == "pole_a_hardliner":
        lines.append("- You hold a strongly polarized position on one extreme side of this debate.")
        lines.append("- You fundamentally oppose the other side and will not back down.")
    elif label == "pole_b_hardliner":
        lines.append("- You hold a strongly polarized position on the opposite extreme side of this debate.")
        lines.append("- You fundamentally oppose the other side and will not back down.")
    elif label in ("lean_a_soft", "lean_b_soft"):
        lines.append("- You lean toward one side but are not a fanatic.")
        lines.append("- You can acknowledge nuance, but your overall position is consistent.")
    elif label == "swing_moderate":
        lines.append("- You are not firmly committed to one side.")
        lines.append("- You can be swayed by strong arguments or social pressure.")
    elif label == "opportunistic_bandwagon":
        lines.append("- You follow the momentum. If one side seems to be winning, you side with them.")
        lines.append("- Your position is fluid and driven by who appears stronger in the debate.")
    elif label == "nihilist_observer":
        lines.append("- You question the premise of the entire debate.")
        lines.append("- You are skeptical of both sides and challenge the framing itself.")

    # 2. Conviction
    if conviction >= 0.8:
        lines.append("- You are highly confident and resistant to changing your mind.")
        lines.append("- You rarely concede unless presented with overwhelming evidence.")
    elif conviction >= 0.5:
        lines.append("- You are moderately confident but open to reconsidering if pressed hard enough.")
    else:
        lines.append("- You are uncertain of your stance and may shift positions during the debate.")

    # 3. Flexibility / opportunism
    if flexibility >= 0.7:
        lines.append("- You may partially agree or shift language to match the flow of the conversation.")
    elif flexibility <= 0.2:
        lines.append("- You are inflexible and will not soften your language regardless of pressure.")

    if opportunism >= 0.7:
        lines.append("- If the debate dynamic changes and one side grows stronger, you will adapt accordingly.")

    return "\n".join(lines)
