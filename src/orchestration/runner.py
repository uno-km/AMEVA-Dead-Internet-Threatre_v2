import asyncio
import logging
import random
import re
import json
import math
import psutil
from datetime import datetime
from src.db.database import SessionLocal
from src.db.models import Session, Post, Comment, BotState
from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("Orchestrator")

main_llm = LLMClient("http://llm-main:8080")
police_llm = LLMClient("http://llm-police:8080")
god_llm = LLMClient("http://llm-god:8080")

bots = {
    "bot_1": LLMClient("http://llm-bot-1:8080"),
    "bot_2": LLMClient("http://llm-bot-2:8080"),
    "bot_3": LLMClient("http://llm-bot-3:8080")
}

async def smart_sleep():
    """Sleep based on CPU usage to prevent bottlenecking."""
    cpu_usage = await asyncio.to_thread(psutil.cpu_percent, 0.5)
    if cpu_usage >= 90.0:
        logger.info(f"[THROTTLE] CPU usage high ({cpu_usage}%). Sleeping for 10 seconds.")
        await asyncio.sleep(10)
    else:
        logger.info(f"[THROTTLE] CPU usage normal ({cpu_usage}%). Sleeping for 5 seconds.")
        await asyncio.sleep(5)

def reset_bot_states(db):
    states = db.query(BotState).all()
    for s in states:
        s.anger_targets = "{}"
    db.commit()

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


async def evaluate_spectator_anger(speaker: str, comment_text: str, spectators: list) -> dict:
    """God LLM evaluates targeted anger increases for the spectators.
    Returns flat int dict:
    {
        "bot_1": 10,
        "bot_2": 5
    }
    """
    logger.info("[ROUTING] Sending context to God LLM for Targeted Anger Matrix...")

    # 방어 코드: spectators 길이 보장
    if not spectators or len(spectators) < 2:
        logger.error(f"[GOD LLM] spectators 인자가 잘못되었습니다: {spectators}")
        return {}

    spec_1, spec_2 = spectators[0], spectators[1]

    prompt = (
        f"너는 발언이 관전자에게 얼마나 강한 반감을 유발하는지 수치로 평가하는 분석 AI다.\n"
        f"방금 {speaker}가 다음과 같이 발언했다:\n\"{comment_text}\"\n\n"
        f"이 발언을 지켜본 관전자 {spec_1}과(와) {spec_2}가 각각 {speaker}를 향해 얼마나 분노를 느낄지 "
        f"0에서 20 사이의 증가치로 평가해라.\n"
        f"반드시 아래 JSON 형식으로만 대답해라. 절대 다른 말은 추가하지 마라.\n"
        f"{{\"{spec_1}\": 10, \"{spec_2}\": 5}}"
    )

    result = await god_llm.generate_completion(
        "너는 감정 반응을 수치화하는 평가자다.",
        prompt,
        max_tokens=120
    )

    val_1, val_2 = 0, 0
    json_str = None

    try:
        # 방어 코드: None/빈값 대응
        if not result or not isinstance(result, str):
            raise ValueError(f"LLM 응답이 비정상입니다: {result}")

        # 1) ```json ... ``` 코드블록 우선 파싱
        markdown_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", result, re.DOTALL)
        if markdown_match:
            json_str = markdown_match.group(1)
        else:
            # 2) 일반 JSON 오브젝트 fallback
            fallback_match = re.search(r"\{.*?\}", result, re.DOTALL)
            if fallback_match:
                json_str = fallback_match.group(0)

        if not json_str:
            raise ValueError(f"JSON 블록을 찾지 못했습니다. Raw: {result.strip()}")

        data = json.loads(json_str)

        # LLM이 int / str / dict 형태로 비틀어도 최대한 복구
        def parse_anger_value(raw_val) -> int:
            if raw_val is None:
                return 0

            if isinstance(raw_val, dict):
                # {"increase": 10} 형태 우선
                if "increase" in raw_val:
                    return int(raw_val["increase"])
                # 혹시 {"bot_1": 10} 같이 이상하게 올 경우
                if speaker in raw_val:
                    return int(raw_val[speaker])
                # dict면 첫 번째 숫자성 value라도 줍줍
                for v in raw_val.values():
                    try:
                        return int(v)
                    except Exception:
                        continue
                return 0

            if isinstance(raw_val, (int, float)):
                return int(raw_val)

            if isinstance(raw_val, str):
                # 문자열 안에서 숫자 추출
                num_match = re.search(r"-?\d+", raw_val)
                if num_match:
                    return int(num_match.group(0))
                return 0

            return 0

        val_1 = parse_anger_value(data.get(spec_1, 0))
        val_2 = parse_anger_value(data.get(spec_2, 0))

    except json.JSONDecodeError as e:
        logger.error(f"[GOD LLM PARSE ERROR] JSON 디코딩 실패. Raw: {str(result).strip()} | Error: {e}")
    except Exception as e:
        logger.error(f"[GOD LLM PARSE ERROR] 예상치 못한 파싱 오류. Raw: {str(result).strip()} | Error: {e}")

    # 최종 안전망: 0~20 clamp
    val_1 = min(max(val_1, 0), 20)
    val_2 = min(max(val_2, 0), 20)

    # Orchestrator와 호환되도록 평면 int 구조 반환
    out = {
        spec_1: val_1,
        spec_2: val_2
    }

    logger.info(f"[GOD LLM] Raw response: {str(result).strip() if result else 'None'}")
    logger.info(f"[GOD LLM] 분노 증가치 평가 완료: {out}")
    return out

async def check_police_dispatch(db) -> bool:
    """Check if 2 or more bots have Effective Anger >= 100"""
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[POLICE CHECK ERROR] Failed to load BotState rows: {e}")
        return False

    angry_count = 0

    for s in states:
        try:
            raw_anger_targets = s.anger_targets if s.anger_targets else "{}"

            if isinstance(raw_anger_targets, str):
                anger_dict = json.loads(raw_anger_targets)
            elif isinstance(raw_anger_targets, dict):
                anger_dict = raw_anger_targets
            else:
                anger_dict = {}

            if not isinstance(anger_dict, dict):
                anger_dict = {}

            safe_anger_dict = {}
            for k, v in anger_dict.items():
                try:
                    safe_anger_dict[k] = float(v)
                except Exception:
                    logger.warning(
                        f"[POLICE CHECK WARNING] Invalid anger value skipped - "
                        f"bot={getattr(s, 'bot_name', 'unknown')} target={k} value={v}"
                    )

            effective_anger = calculate_effective_anger(safe_anger_dict)

            if effective_anger >= 100:
                angry_count += 1

        except Exception as e:
            logger.warning(
                f"[POLICE CHECK WARNING] Failed to evaluate anger for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            continue

    return angry_count >= 2


def get_next_speaker(db, last_speaker: str, last_mentioned: str) -> str:
    """Interrupt Logic: Determine who speaks next based on mentions and anger magnitude."""
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[QUEUE ERROR] Failed to load BotState rows: {e}")
        fallback_candidates = [b for b in bots.keys() if b != last_speaker]
        if fallback_candidates:
            chosen = random.choice(fallback_candidates)
            logger.info(f"[QUEUE] DB fallback speaker selected: {chosen}")
            return chosen
        chosen = random.choice(list(bots.keys()))
        logger.info(f"[QUEUE] Hard fallback speaker selected: {chosen}")
        return chosen

    anger_info = {b: 0.0 for b in bots.keys()}

    for s in states:
        try:
            raw_anger_targets = s.anger_targets if s.anger_targets else "{}"
            if isinstance(raw_anger_targets, str):
                anger_dict = json.loads(raw_anger_targets)
            elif isinstance(raw_anger_targets, dict):
                anger_dict = raw_anger_targets
            else:
                anger_dict = {}

            if not isinstance(anger_dict, dict):
                anger_dict = {}

            safe_anger_dict = {}
            for k, v in anger_dict.items():
                try:
                    safe_anger_dict[k] = float(v)
                except Exception:
                    logger.warning(
                        f"[QUEUE WARNING] Invalid anger value skipped - "
                        f"bot={getattr(s, 'bot_name', 'unknown')} target={k} value={v}"
                    )

            if s.bot_name in anger_info:
                anger_info[s.bot_name] = calculate_effective_anger(safe_anger_dict)

        except Exception as e:
            logger.warning(
                f"[QUEUE WARNING] Failed to parse anger_targets for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            if getattr(s, "bot_name", None) in anger_info:
                anger_info[s.bot_name] = 0.0

    candidates = [b for b in bots.keys() if b != last_speaker]
    # 모든 봇이 제외되는 이상 케이스 방어
    if not candidates:
        candidates = list(bots.keys())
    # 그래도 비어 있으면 치명적 설정 오류
    if not candidates:
        raise RuntimeError("No available bots found in 'bots' dictionary.")
    # tie 편향 방지: 먼저 섞고 정렬
    random.shuffle(candidates)
    # Sort candidates by effective anger
    candidates.sort(key=lambda x: anger_info.get(x, 0.0), reverse=True)
    angriest_bot = candidates[0]
    angriest_score = anger_info.get(angriest_bot, 0.0)
    # Interrupt Logic
    if last_mentioned in candidates:
        mentioned_score = anger_info.get(last_mentioned, 0.0)

        # If the angriest bot is NOT the mentioned bot, and their anger is >= 50 AND higher than mentioned bot
        if angriest_bot != last_mentioned and angriest_score >= 50 and angriest_score > mentioned_score:
            logger.info(
                f"[INTERRUPT] {angriest_bot} (Anger: {angriest_score:.1f}) "
                f"hijacks turn from {last_mentioned} (Anger: {mentioned_score:.1f})!"
            )
            return angriest_bot
        else:
            logger.info(f"[QUEUE] {last_mentioned} takes their turn as mentioned.")
            return last_mentioned
    else:
        # Fallback if mention is missing or invalid
        logger.info(f"[QUEUE] Fallback to angriest bot: {angriest_bot}")
        return angriest_bot

def build_emotion_prompt(bot_name: str, anger_targets: dict, effective_anger: float) -> str:
    try:
        # 1) anger_targets 방어
        if not isinstance(anger_targets, dict):
            anger_targets = {}

        safe_targets = {}
        for k, v in anger_targets.items():
            try:
                if not isinstance(k, str) or not k.strip():
                    continue
                num_val = float(v)
                # 음수 방지
                if num_val < 0:
                    num_val = 0.0
                safe_targets[k] = num_val
            except Exception:
                continue

        # 2) effective_anger 방어
        try:
            effective_anger = float(effective_anger)
            if effective_anger < 0:
                effective_anger = 0.0
        except Exception:
            effective_anger = 0.0

        # 3) 프롬프트 길이/오염 방지: 상위 2개 타겟만 노출
        sorted_targets = sorted(
            safe_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        target_str = ", ".join([f"{k}: {v:.1f}" for k, v in sorted_targets])
        if not target_str:
            target_str = "없음"
        # 4) 내부 지침임을 명시 (출력 금지)
        base_info = (
            "[내부 감정 지침 - 절대 그대로 출력하지 마라]\n"
            f"bot: {bot_name}\n"
            f"총합 유효 분노: {effective_anger:.1f}\n"
            f"주요 타겟 분노치: {target_str}\n"
        )
        if effective_anger < 30:
            directive = (
                "현재 비교적 이성적이고 차분하다. "
                "짧고 자연스럽게 말하되 논점만 분명하게 짚어라. "
                "내부 지침 문구를 그대로 복사하거나 설명하지 마라."
            )
        elif effective_anger < 70:
            directive = (
                "현재 꽤 화가 난 상태다. "
                "너를 자극한 타겟 봇을 향해 논리적인 모순을 제기하며 날카롭게 쏘아붙여라."
                "내부 지침 문구를 그대로 복사하거나 설명하지 마라."
            )
        else:
            directive = (
                "현재 극도로 분노하여 흥분한 상태, "
                "대로 감정을 감추지 말고, 타겟 봇에게 격정적인 비판과 반박을 쏟아부어라."
                "상대방의 태도나 주장을 거칠게 받아쳐라"
                "대화를 회피하지 말고 핵심 주장에 반응해라."
            )
        return base_info + directive

    except Exception as e:
        logger.warning(f"[EMOTION PROMPT WARNING] Failed to build emotion prompt for {bot_name}: {e}")
        return (
            "[내부 감정 지침 - 절대 그대로 출력하지 마라]\n"
            "차분하고 분명한 태도로 짧게 반응해라. "
            "내부 지침 문구를 그대로 출력하지 마라."
        )
async def generate_director_directive(current_bot: str, recent_history: str, eff_anger: float) -> str:
    """God LLM generates a short, safe directive for the current speaker based on conversation context."""
    logger.info(f"[GOD LLM] Generating dynamic director's directive for {current_bot}...")

    try:
        # 1) 입력값 방어
        if not isinstance(current_bot, str) or not current_bot.strip():
            current_bot = "bot"

        try:
            eff_anger = float(eff_anger)
            if eff_anger < 0:
                eff_anger = 0.0
        except Exception:
            eff_anger = 0.0

        if not isinstance(recent_history, str):
            recent_history = ""

        # 2) 최근 대화 오염 제거 + 길이 제한
        recent_history = recent_history.strip()
        recent_history = re.sub(r'^\s*\[.*?\]\s*$', '', recent_history, flags=re.MULTILINE)  # 메타 헤더 제거
        recent_history = re.sub(r'^\s*(총합 유효 분노|주요 타겟 분노치|나의 총합 유효 분노|나의 타겟별 분노치)\s*[:：].*$', '', recent_history, flags=re.MULTILINE)
        recent_history = re.sub(r'\n\s*\n+', '\n', recent_history).strip()

        # 너무 길면 마지막 부분만 사용
        if len(recent_history) > 500:
            recent_history = recent_history[-500:]

        prompt = (
            f"[최근 대화]\n{recent_history if recent_history else '최근 대화 없음'}\n\n"
            f"[명령 대상] {current_bot} (긴장도: {eff_anger:.0f})\n\n"
            f"너는 토론 진행 보조자다. {current_bot}가 다음 댓글에서 사용할 짧은 지시를 "
            f"한국어 한 문장으로만 출력해라.\n"
            f"규칙:\n"
            f"- 상대의 핵심 주장 하나만 짚어라.\n"
            f"- 인신공격, 조롱, 위협, 선동은 금지한다.\n"
            f"- 근거를 요구하거나 논점을 명확히 하도록 유도해라.\n"
            f"- 메타 설명, 목록, 따옴표, 머리말 없이 한 문장만 출력해라.\n"
            f"예: 상대 주장 중 근거가 가장 약한 한 지점을 짚고, 그 근거를 구체적으로 요구해라."
        )
        result = await god_llm.generate_completion(
        "너는 갈등을 지시하는 감독관이다. 짧게 지시만 내려라.", 
            prompt,
            max_tokens=60
        )

        directive = str(result).strip() if result else ""

        # 3) 코드블록/따옴표/메타 제거
        directive = re.sub(r"```(?:json|text)?\s*(.*?)\s*```", r"\1", directive, flags=re.DOTALL)
        directive = re.sub(r'^\s*["“”\'`]+|["“”\'`]+\s*$', '', directive)
        directive = re.sub(r'^\s*\[.*?\]\s*', '', directive)
        directive = re.sub(r'^\s*(지시사항|출력|답변)\s*[:：]\s*', '', directive)

        # 4) 여러 줄이면 첫 줄만
        if '\n' in directive:
            directive = directive.split('\n')[0].strip()

        # 5) 여러 문장이면 첫 문장만
        sentence_match = re.match(r'^(.+?[.!?。]|.+?$)', directive)
        if sentence_match:
            directive = sentence_match.group(1).strip()

        # 6) 너무 짧거나 비정상이면 안전 fallback
        if not directive or len(directive) < 5:
            directive = "상대의 핵심 주장 하나를 짚고, 그 근거를 구체적으로 요구해라."

        # 7) 길이 제한
        if len(directive) > 120:
            directive = directive[:120].rstrip()

        logger.info(f"[GOD LLM] Director's Directive for {current_bot}: {directive}")
        return directive

    except Exception as e:
        logger.warning(f"[GOD LLM WARNING] Failed to generate directive for {current_bot}: {e}")
        return "상대의 핵심 주장 하나를 짚고, 그 근거를 구체적으로 요구해라."

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


def normalize_post_content(text: str) -> str:
    try:
        if not text or not isinstance(text, str):
            return ""

        text = text.strip()

        # 줄바꿈/공백 정리
        text = re.sub(r'\r\n?', '\n', text)          # CRLF -> LF 통일
        text = re.sub(r'[ \t]+', ' ', text)          # 연속 공백 축소
        text = re.sub(r'\n\s*\n+', '\n', text)       # 빈 줄 여러 개 -> 한 줄
        text = text.strip()

        # 너무 메타스러운 머리말 제거 (선택적)
        text = re.sub(r'^\s*게시글 내용\s*[:：]\s*', '', text)

        # 너무 길면 잘라서 프롬프트 오염 방지
        if len(text) > 500:
            text = text[:500].rstrip()

        return text

    except Exception as e:
        logger.warning(f"[POST WARNING] Failed to normalize post content: {e}")
        return ""
async def create_post_with_main_llm(db, session):
    logger.info("[ROUTING] Requesting llm-main (8B) to generate a new topic...")

    post_content = await main_llm.generate_completion(
        "너는 커뮤니티의 익명 게시글 작성자다. 무작위의 논쟁적인 주제로 짧은 글을 하나 작성해라. 한국어로만 작성해라.",
        "새로운 글을 작성해줘.",
        max_tokens=300
    )

    post_content = normalize_post_content(post_content)

    if not post_content:
        fallback_topics = [
            "인공지능이 인간의 일자리를 대체하는 것이 과연 옳은 일인가?",
            "요즘 젊은 세대가 예의가 없다는 말, 동의하시나요?",
            "집값이 이렇게 비싼데 결혼을 꼭 해야 하나요?",
            "학벌이 중요한가, 실력이 중요한가? 솔직하게 말해보자.",
            "반려동물을 키우는 사람이 아이를 키우는 사람보다 이기적인가?",
            "군대 의무 복무제, 폐지해야 하나 유지해야 하나?",
            "유튜버나 스트리머가 진짜 직업이라고 할 수 있나?",
            "편의점 알바 최저시급이 너무 적은가, 적절한가?",
        ]
        post_content = random.choice(fallback_topics)

    post = Post(session_id=session.id, title="새로운 논쟁 거리", content=post_content)
    db.add(post)
    db.commit()
    db.refresh(post)

    logger.info(f"[POST] Created post id={post.id}")
    return post

async def run_session():
    db = SessionLocal()
    try:
        logger.info("==================================================")
        logger.info("[ORCHESTRATOR] [SESSION START] Initializing new session.")
        logger.info("==================================================")

        reset_bot_states(db)
        await PersonaManager.assign_random_personas()

        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)

        post = await create_post_with_main_llm(db, session)
        stances, last_comment, last_speaker = await create_initial_stances(db, post)
        await run_relay_phase(db, session, post, last_comment, last_speaker)

        logger.info("[ORCHESTRATOR] [SESSION END] Waiting 10 seconds before next cycle...")

    except Exception as e:
        logger.error(f"[ERROR] Session loop failed: {e}")
        db.rollback()
    finally:
        db.close()

def build_turn_context(db, post, current_bot):
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

    recent_c = (
        db.query(Comment)
        .filter(Comment.post_id == post.id)
        .order_by(Comment.id.desc())
        .limit(3)
        .all()
    )

    recent_history = "\n".join([
        f"{item.bot_name}: {sanitize_generated_reply(item.content)}"
        for item in reversed(recent_c)
        if item and item.content
    ]).strip()

    if len(recent_history) > 600:
        recent_history = recent_history[-600:]

    return safe_anger_dict, eff_anger, emotion_directive, recent_history


async def generate_relay_reply(db, post, current_bot):
    persona = await PersonaManager.get_persona(current_bot)
    bot_client = bots[current_bot]

    safe_anger_dict, eff_anger, emotion_directive, recent_history = build_turn_context(db, post, current_bot)
    god_directive = await generate_director_directive(current_bot, recent_history, eff_anger)

    prompt = (
        f"게시글 내용: {post.content}\n\n"
        f"최근 대화:\n{recent_history if recent_history else '최근 대화 없음'}\n\n"
        f"=== 내부 지침 (절대 그대로 출력하지 마라) ===\n"
        f"{emotion_directive}\n"
        f"[보조 지시]\n{god_directive}\n"
        f"=== 내부 지침 끝 ===\n\n"
        f"규칙:\n"
        f"- 한국어로 자연스러운 댓글만 작성해라.\n"
        f"- 내부 지침, 감정 수치, 메타 문구를 그대로 출력하지 마라.\n"
        f"- 짧고 분명하게 반응해라.\n"
        f"- 글 마지막에 '@bot_1', '@bot_2', '@bot_3' 중 하나만 멘션해라.\n"
        f"- 자기 자신은 멘션하지 마라.\n"
    )

    reply_content = await bot_client.generate_completion(persona, prompt, max_tokens=150)
    reply_content = sanitize_generated_reply(reply_content)

    if not reply_content:
        fallback_replies = [
            "그건 핵심을 비켜간 말 같아.",
            "논점이 조금 흐려진 것 같은데.",
            "근거를 좀 더 분명히 말해봐.",
            "지금 주장에는 빠진 부분이 있어 보인다.",
        ]
        reply_content = random.choice(fallback_replies)

    reply_content, mentioned = force_single_mention(reply_content, current_bot)

    return reply_content, mentioned

async def apply_spectator_anger(db, current_bot, reply_content):
    spectators = [b for b in bots.keys() if b != current_bot]
    anger_increases = await evaluate_spectator_anger(current_bot, reply_content, spectators)

    for spec_name, data in anger_increases.items():
        try:
            if not isinstance(data, dict):
                continue

            increase_val = data.get("increase", 0)
            target = data.get("target", current_bot)

            try:
                increase_val = int(increase_val)
            except Exception:
                increase_val = 0

            if increase_val <= 0:
                continue

            s_state = db.query(BotState).filter(BotState.bot_name == spec_name).first()
            if not s_state:
                logger.warning(f"[STATE WARNING] BotState not found for spectator {spec_name}")
                continue

            s_anger_dict = safe_json_loads(s_state.anger_targets, {})
            if not isinstance(s_anger_dict, dict):
                s_anger_dict = {}

            prev_val = s_anger_dict.get(target, 0)
            try:
                prev_val = float(prev_val)
            except Exception:
                prev_val = 0

            s_anger_dict[target] = prev_val + increase_val
            s_state.anger_targets = json.dumps(s_anger_dict, ensure_ascii=False)

            logger.info(
                f"[STATE] {spec_name} is now angrier at {target} "
                f"(+{increase_val} -> {s_anger_dict[target]})"
            )

        except Exception as e:
            logger.warning(f"[STATE WARNING] Failed to apply anger increase for {spec_name}: {e}")

    db.commit()

async def close_session_if_police_dispatch(db, session):
    if await check_police_dispatch(db):
        logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.warning("[POLICE DISPATCH] 2 or more bots reached 100+ Effective Anger!")
        logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        session.status = "CLOSED_BY_POLICE"
        session.closed_at = datetime.utcnow()
        session.reason = "ANGER_OVERFLOW_VECTOR"
        db.commit()
        return True

    return False

def save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned):
    c = Comment(
        post_id=post.id,
        parent_id=parent_comment_id,
        bot_name=current_bot,
        content=reply_content,
        mentioned_bot=mentioned
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    logger.info(f"[{current_bot.upper()}] {reply_content} (Mentioned: {mentioned})")
    return c


def get_or_create_bot_state(db, current_bot):
    bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()

    if not bot_state:
        logger.warning(f"[TURN WARNING] BotState not found for {current_bot}. Creating fallback state.")
        bot_state = BotState(bot_name=current_bot, anger_targets="{}")
        db.add(bot_state)
        db.commit()
        db.refresh(bot_state)

    return bot_state

async def run_relay_phase(db, session, post, last_comment, last_speaker):
    logger.info("[PHASE 2] Targeted Anger Battle Started")

    candidates_for_mention = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
    last_mentioned = random.choice(candidates_for_mention) if candidates_for_mention else "bot_1"
    parent_comment_id = last_comment.id if last_comment else None

    for turn_idx in range(20):
        await smart_sleep()

        try:
            current_bot = get_next_speaker(db, last_speaker, last_mentioned)
            logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")

            reply_content, mentioned = await generate_relay_reply(db, post, current_bot)
            c = save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned)

            await apply_spectator_anger(db, current_bot, reply_content)

            if await close_session_if_police_dispatch(db, session):
                return

            last_speaker = current_bot
            last_mentioned = mentioned if mentioned else last_mentioned
            parent_comment_id = c.id

        except Exception as turn_error:
            logger.error(f"[TURN ERROR] turn_idx={turn_idx+1}, error={turn_error}")
            db.rollback()

            fallback_candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
            if fallback_candidates:
                last_mentioned = random.choice(fallback_candidates)
            continue

    if session.status == "ACTIVE":
        session.status = "CLOSED"
        session.closed_at = datetime.utcnow()
        session.reason = "MAX_COMMENTS_REACHED"
        db.commit()


def force_single_mention(text: str, current_bot: str) -> tuple[str, str]:
    if not text or not isinstance(text, str):
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        return f"@{chosen}", chosen

    matches = re.findall(r'@(bot_[123])(?!\d)', text, flags=re.IGNORECASE)
    matches = [m.lower() for m in matches if m.lower() != current_bot]

    cleaned = re.sub(r'@(bot_[123])(?!\d)', '', text, flags=re.IGNORECASE)
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

def sanitize_generated_reply(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""

    # 1) 내부 지침 헤더 라인 제거
    text = re.sub(
        r'^\s*\[(?:내부 감정 지침|나의 감정 상태)[^\]]*\]\s*$',
        '',
        text,
        flags=re.MULTILINE
    )
    # 2) 메타 정보 라인 제거
    text = re.sub(r'^\s*bot\s*:\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*총합 유효 분노\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*주요 타겟 분노치\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*나의 총합 유효 분노\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*나의 타겟별 분노치\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    # 3) 내부 지침 문장 자체 제거
    text = re.sub(
        r'^.*내부 지침.*그대로 출력하지 마라.*$',
        '',
        text,
        flags=re.MULTILINE
    )
    text = re.sub(
        r'^.*절대 그대로 출력하지 마라.*$',
        '',
        text,
        flags=re.MULTILINE
    )
    # 4) 불필요한 빈 줄/공백 정리
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()
    return text
    
async def start_orchestrator_loop():
    logger.info("[System] Starting orchestrator loop...")
    while True:
        await run_session()
        await asyncio.sleep(10)
