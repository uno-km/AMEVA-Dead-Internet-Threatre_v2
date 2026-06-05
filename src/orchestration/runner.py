import asyncio
import logging
import random
import re
import json
import math

import subprocess
import time
import urllib.request
import urllib.error

import psutil
from datetime import datetime
from contextlib import asynccontextmanager
from src.db.database import SessionLocal
from src.db.models import Session, Post, Comment, BotState, SessionBotState
from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager
from src.orchestration.state_manager import state_manager, SystemState, Checkpoint

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("Orchestrator")

main_llm = LLMClient("http://localhost:8101")
#police_llm = LLMClient("http://localhost:8106")
god_llm = LLMClient("http://localhost:8105")

bots = {
    "bot_1": LLMClient("http://localhost:8102"),
    "bot_2": LLMClient("http://localhost:8103"),
    "bot_3": LLMClient("http://localhost:8104")
}

def docker_start(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "start", container_name],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"[DOCKER] start ok: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"[DOCKER] start failed: {e.stderr.strip()}")
        return False


def docker_stop(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "stop", container_name],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"[DOCKER] stop ok: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()

        if "is not running" in stderr or "is not running" in stdout:
            logger.info(f"[DOCKER] stop skipped: {container_name} already stopped")
            return True

        logger.error(f"[DOCKER] stop failed: {stderr or stdout}")
        return False


async def wait_for_http_ready(url: str, timeout: int = 120, interval: int = 2) -> bool:
    start_time = time.time()

    while time.time() - start_time < timeout:
        if state_manager.state == SystemState.STOPPING:
            logger.info(f"[HEALTH] STOPPING state detected. Aborting wait for {url}.")
            return False
            
        try:
            def _probe():
                with urllib.request.urlopen(url, timeout=5) as response:
                    return response.status

            status_code = await asyncio.to_thread(_probe)
            if 200 <= status_code < 500:
                logger.info(f"[HEALTH] endpoint ready: {url} status={status_code}")
                return True
        except urllib.error.HTTPError as e:
            # 404여도 서버 프로세스 자체는 살아있을 수 있으니 ready로 볼 수 있음
            if 400 <= e.code < 500:
                logger.info(f"[HEALTH] endpoint responding: {url} status={e.code}")
                return True
        except Exception:
            pass

        logger.info(f"[HEALTH] waiting for endpoint: {url}")
        await asyncio.sleep(interval)

    logger.error(f"[HEALTH] timeout waiting for endpoint: {url}")
    return False

async def close_session_if_any_metric_exceeded(db, session, threshold: float = 120.0) -> bool:
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[THRESHOLD CHECK ERROR] Failed to load BotState rows: {e}")
        return False

    for s in states:
        try:
            metric_dict = safe_json_loads(s.anger_targets, {})
            if not isinstance(metric_dict, dict):
                metric_dict = {}

            effective_metric = calculate_effective_anger(metric_dict)

            if effective_metric >= threshold:
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                logger.warning(
                    f"[SESSION CLOSE] {getattr(s, 'bot_name', 'unknown')} exceeded threshold "
                    f"({effective_metric:.1f} >= {threshold})"
                )
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                session.status = "CLOSED_BY_THRESHOLD"
                session.closed_at = datetime.now()
                session.reason = f"METRIC_THRESHOLD_{int(threshold)}"
                db.commit()
                return True

        except Exception as e:
            logger.warning(
                f"[THRESHOLD CHECK WARNING] Failed to evaluate metric for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            continue

    return False

@asynccontextmanager
async def llm_lifecycle(container_name: str, port: int, timeout: int = 120):
    """
    지정된 도커 컨테이너를 시작하고, 헬스체크 대기 후 실행 컨텍스트를 제공.
    블록을 빠져나오면 자원을 반납(종료)함.
    """
    ready_url = f"http://localhost:{port}/health"
    try:
        docker_start(container_name)
        ready = await wait_for_http_ready(ready_url, timeout=timeout, interval=2)
        if not ready:
            logger.warning(f"[LIFECYCLE] {container_name} 가 제한시간 내에 준비되지 않았습니다.")
        yield ready
    finally:
        docker_stop(container_name)

@asynccontextmanager
async def multi_llm_lifecycle(targets, timeout: int = 120):
    """
    여러 컨테이너를 한 번에 시작하고, 블록 종료 시 모두 정리한다.
    targets = [("ameva-llm-bot-1", 8102), ...]
    """
    started = []
    try:
        for container_name, port in targets:
            docker_start(container_name)
            started.append((container_name, port))

        for container_name, port in started:
            ready_url = f"http://localhost:{port}/health"
            ready = await wait_for_http_ready(ready_url, timeout=timeout, interval=2)
            if not ready:
                logger.warning(f"[LIFECYCLE] {container_name} 가 제한시간 내 준비되지 않았습니다.")

        yield True
    finally:
        for container_name, _ in reversed(started):
            docker_stop(container_name)

async def smart_sleep():
    """Sleep based on CPU usage to prevent bottlenecking."""
    if state_manager.state == SystemState.STOPPING:
        return
        
    cpu_usage = await asyncio.to_thread(psutil.cpu_percent, 0.5)
    
    if state_manager.state == SystemState.STOPPING:
        return
        
    if cpu_usage >= 90.0:
        logger.info(f"[THROTTLE] CPU usage high ({cpu_usage}%). Sleeping for 10 seconds.")
        # 간격 단위로 쪼개어 STOPPING 상태를 지속 감시
        for _ in range(10):
            if state_manager.state == SystemState.STOPPING:
                return
            await asyncio.sleep(1)
    else:
        logger.info(f"[THROTTLE] CPU usage normal ({cpu_usage}%). Sleeping for 5 seconds.")
        for _ in range(5):
            if state_manager.state == SystemState.STOPPING:
                return
            await asyncio.sleep(1)

def reset_bot_states(db):
    states = db.query(BotState).all()
    for s in states:
        s.anger_targets = "{}"
    db.commit()

async def sync_personas_to_db(db):
    persona_map = await PersonaManager.get_all_personas()
    for bot_name, persona in persona_map.items():
        row = db.query(BotState).filter(BotState.bot_name == bot_name).first()
        if not row:
            row = BotState(bot_name=bot_name, anger_targets="{}")
            db.add(row)
        row.persona = persona
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
    Returns nested dict:
    {
        "bot_1": {"increase": 10, "target": "bot_3"},
        "bot_2": {"increase": 5, "target": "bot_3"}
    }
    """
    logger.info("[ROUTING] Sending context to God LLM for Targeted Anger Matrix...")

    if not spectators or len(spectators) < 2:
        logger.error(f"[GOD LLM] spectators 인자가 잘못되었습니다: {spectators}")
        return {}

    spec_1, spec_2 = spectators[0], spectators[1]

    prompt = (
        f"You are an analysis AI evaluating how much a speaker's statement provokes anger in spectators.\n"
        f"Speaker {speaker} just said:\n\"{comment_text}\"\n\n"
        f"Evaluate how much anger the spectators {spec_1} and {spec_2} will feel towards {speaker} based on this statement. "
        f"Provide an anger increase value between 0 and 20.\n"
        f"You MUST output ONLY valid JSON in the exact format below, with no other text:\n"
        f"{{"
        f"\"{spec_1}\": {{\"increase\": 10, \"target\": \"{speaker}\"}}, "
        f"\"{spec_2}\": {{\"increase\": 5, \"target\": \"{speaker}\"}}"
        f"}}"
    )

    result = await god_llm.generate_completion(
        "You are an AI that quantifies emotional reactions.",
        prompt,
        max_tokens=150
    )

    val_1, val_2 = 0, 0
    target_1, target_2 = speaker, speaker
    json_str = None

    try:
        if not result or not isinstance(result, str):
            raise ValueError(f"LLM 응답이 비정상입니다: {result}")

        candidate = result.strip()
        # 1) ```json ... ``` 우선
        
        markdown_match = re.search(r"```(?:json)?\s*(.*?)\s*```", result, re.DOTALL)
        if markdown_match:
            candidate = markdown_match.group(1).strip()

        start_idx = candidate.find("{")
        end_idx = candidate.rfind("}")

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = candidate[start_idx:end_idx + 1]
        else:
            # 2) 일반 JSON fallback
            fallback_match = re.search(r"\{.*\}", result, re.DOTALL)
            if fallback_match:
                json_str = fallback_match.group(0)

        if not json_str:
            raise ValueError(f"JSON 블록을 찾지 못했습니다. Raw: {result.strip()}")

        data = json.loads(json_str)

        def parse_entry(raw_val, default_target):
            increase = 0
            target = default_target

            if raw_val is None:
                return increase, target

            if isinstance(raw_val, dict):
                # {"increase": 10, "target": "bot_3"}
                try:
                    increase = int(raw_val.get("increase", 0))
                except Exception:
                    increase = 0

                raw_target = raw_val.get("target", default_target)
                if isinstance(raw_target, str) and raw_target.strip():
                    target = raw_target.strip()
                return increase, target

            # 만약 LLM이 그냥 숫자만 줬으면
            if isinstance(raw_val, (int, float)):
                return int(raw_val), target

            if isinstance(raw_val, str):
                num_match = re.search(r"-?\d+", raw_val)
                if num_match:
                    increase = int(num_match.group(0))
                return increase, target

            return increase, target

        if isinstance(data, dict):
            val_1, target_1 = parse_entry(data.get(spec_1, 0), speaker)
            val_2, target_2 = parse_entry(data.get(spec_2, 0), speaker)

    except json.JSONDecodeError as e:
        logger.error(f"[GOD LLM PARSE ERROR] JSON 디코딩 실패. Raw: {str(result).strip()} | Error: {e}")
    except Exception as e:
        logger.error(f"[GOD LLM PARSE ERROR] 예상치 못한 파싱 오류. Raw: {str(result).strip()} | Error: {e}")

    # clamp
    val_1 = min(max(val_1, 0), 20)
    val_2 = min(max(val_2, 0), 20)

    out = {
        spec_1: {
            "increase": val_1,
            "target": target_1 if target_1 in bots else speaker
        },
        spec_2: {
            "increase": val_2,
            "target": target_2 if target_2 in bots else speaker
        }
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
async def generate_director_directive(db, current_bot: str, recent_history: str, eff_anger: float) -> str:
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
            directive = "Point out one of the opponent's core arguments and specifically demand evidence for it."

        # 7) 길이 제한
        if len(directive) > 120:
            directive = directive[:120].rstrip()
            
        bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
        if bot_state:
            bot_state.current_directive = directive
            db.commit()

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

        return text

    except Exception as e:
        logger.warning(f"[POST WARNING] Failed to normalize post content: {e}")
        return ""

async def create_post_with_main_llm(db, session):
    logger.info("[ROUTING] Requesting llm-main (8B) to generate a new topic...")

    post_content = ""
    title = "새로운 논쟁 거리"

    try:
        async with llm_lifecycle("ameva-llm-main", 8101, timeout=180) as is_ready:
            if not is_ready:
                logger.warning("[LLM-MAIN] main container was not ready. Falling back to static topics.")
            else:
                prompt = (
                    "You are an anonymous community forum user. Write a highly engaging, catchy, and controversial post on a random trending/opinionated topic. Write in English only.\n"
                    "You MUST output your response ONLY as a valid JSON object in the exact format below, with no other text:\n"
                    "{\n"
                    '  "title": "A highly compelling and controversial title",\n'
                    '  "content": "Your post content details..."\n'
                    "}"
                )
                result = await main_llm.generate_completion(
                    "You are an AI that writes forum posts. You only respond in JSON format.",
                    prompt,
                    max_tokens=500,
                    timeout=180.0,
                    response_format={"type": "json_object"}
                )
                
                # JSON 파싱 시도
                if result:
                    result = result.strip()
                    json_str = None
                    markdown_match = re.search(r"```(?:json)?\s*(.*?)\s*```", result, re.DOTALL)
                    if markdown_match:
                        json_str = markdown_match.group(1).strip()
                    else:
                        start_idx = result.find("{")
                        end_idx = result.rfind("}")
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = result[start_idx:end_idx + 1]
                    
                    if json_str:
                        try:
                            data = json.loads(json_str)
                            title = data.get("title", title).strip()
                            post_content = data.get("content", "").strip()
                        except json.JSONDecodeError as e:
                            logger.error(f"[LLM-MAIN] JSON 디코딩 실패. Raw: {result} | Error: {e}")
                    else:
                        logger.error(f"[LLM-MAIN] JSON 블록을 찾지 못했습니다. Raw: {result}")
    except Exception as e:
        logger.error(f"[LLM-MAIN] Error generating topic: {e}")

    # Fallback 로직
    if not post_content:
        fallback_topics = [
            ("AI and Jobs", "Is it really a good thing that AI is replacing human jobs?"),
            ("Modern Manners", "Do you agree that the younger generation has no manners these days?"),
            ("Marriage in Modern Times", "With housing prices so high, is marriage really necessary?"),
            ("Pedigree vs Skills", "What's more important: academic pedigree or actual skills? Let's be honest."),
            ("Pets vs Children", "Are people who raise pets more selfish than people who raise children?"),
            ("Military Service", "Should mandatory military service be abolished or maintained?"),
            ("Content Creators", "Can being a YouTuber or streamer really be considered a real job?"),
            ("Minimum Wage", "Is the minimum wage for convenience store workers too low, or appropriate?"),
        ]
        fallback_item = random.choice(fallback_topics)
        title = fallback_item[0]
        post_content = fallback_item[1]

    post_content = normalize_post_content(post_content)

    post = Post(session_id=session.id, title=title, content=post_content)
    db.add(post)
    db.commit()
    db.refresh(post)

    logger.info(f"[POST] Created post id={post.id} with title={title}")
    return post


async def run_session():
    db = SessionLocal()
    try:
        logger.info("==================================================")
        logger.info("[ORCHESTRATOR] [SESSION START] Initializing new session.")
        logger.info("==================================================")

        reset_bot_states(db)
        await PersonaManager.assign_random_personas()
        await sync_personas_to_db(db)

        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)

        state_manager.current_session_id = session.id
        post = await create_post_with_main_llm(db, session)
        await state_manager.wait_at_checkpoint(Checkpoint.TOPIC_GEN_DONE)

        # 신 LLM 및 봇들을 아고라(초기 의견 + 릴레이) 내내 상시 켜둠
        bot_targets = [
            ("ameva-llm-bot-1", 8102),
            ("ameva-llm-bot-2", 8103),
            ("ameva-llm-bot-3", 8104),
        ]
        
        async with llm_lifecycle("ameva-llm-god", 8105):
            async with multi_llm_lifecycle(bot_targets):
                stances, last_comment, last_speaker = await create_initial_stances(db, post)
                await state_manager.wait_at_checkpoint(Checkpoint.PHASE1_DONE)

                await run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=0)

        logger.info("[ORCHESTRATOR] [SESSION END] Completed relay phase.")
        state_manager.set_state(SystemState.IDLE)
        state_manager.checkpoint = Checkpoint.NONE

    except InterruptedError:
        logger.info("[ORCHESTRATOR] Session stopped via command.")
        state_manager.set_state(SystemState.IDLE)
    except Exception as e:
        logger.error(f"[ERROR] Session loop failed: {e}")
        db.rollback()
        state_manager.set_state(SystemState.IDLE)
    finally:
        db.close()

async def create_initial_stances(db, post):
    logger.info("[PHASE 1] Initial Stance Declaration (Sequential & Random)")

    stances = []
    initial_order = ["bot_1", "bot_2", "bot_3"]

    for b_name in initial_order:
        if state_manager.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")
            
        await smart_sleep()
        try:
            persona = await PersonaManager.get_persona(b_name)
            bot_client = bots[b_name]

            prompt = (
                f"Post Content: {post.content}\n\n"
                f"Instruction: State your position on the above post clearly and concisely in 1-2 sentences. Reply in English.\n"
            )

            reply_content = await bot_client.generate_completion(
                persona,
                prompt,
                max_tokens=120
            )

            reply_content = sanitize_generated_reply(reply_content)

            if not reply_content:
                fallback_stances = [
                    "나는 이 문제를 꽤 중요하게 본다.",
                    "이건 생각보다 의견이 갈릴 만한 주제다.",
                    "내 입장은 비교적 분명한 편이다.",
                    "겉보기보다 논점이 복잡한 문제라고 본다.",
                ]
                reply_content = random.choice(fallback_stances)

            stances.append((b_name, reply_content))

        except Exception as e:
            logger.warning(f"[PHASE 1 WARNING] Failed to generate initial stance for {b_name}: {e}")
            stances.append((b_name, "이 주제는 입장이 갈릴 수밖에 없다고 본다."))

    # DB 삽입 순서 랜덤화
    random.shuffle(stances)

    last_comment = None
    last_speaker = None

    for b_name, reply_content in stances:
        c = Comment(
            post_id=post.id,
            parent_id=None,
            bot_name=b_name,
            content=reply_content
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        logger.info(f"[{b_name.upper()}] Initial Stance: {reply_content}")
        last_comment = c
        last_speaker = b_name

    if not last_speaker:
        last_speaker = random.choice(initial_order)

    return stances, last_comment, last_speaker

async def build_turn_context(db, post, current_bot, use_structured=False):
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


async def generate_relay_reply(db, post, current_bot, turn_idx=0):
    import os
    persona = await PersonaManager.get_persona(current_bot)
    bot_client = bots[current_bot]

    # [LPDE Feature Flags]
    LPDE_STRUCTURED_HISTORY = os.getenv("LPDE_STRUCTURED_HISTORY", "true").lower() == "true"
    LPDE_FULL_PROMPT = os.getenv("LPDE_FULL_PROMPT", "false").lower() == "true"
    LPDE_LEGACY_PROMPT = os.getenv("LPDE_LEGACY_PROMPT", "false").lower() == "true"

    # [LPDE Phase 1A] Shadow Mode Update
    from src.core.personality_engine import personality_engine
    personality_engine.update_fast_state(db, post.session_id, current_bot, turn_index=turn_idx)

    safe_anger_dict, eff_anger, emotion_directive, recent_history = await build_turn_context(
        db, post, current_bot, use_structured=LPDE_STRUCTURED_HISTORY
    )
    god_directive = await generate_director_directive(db, current_bot, recent_history, eff_anger)

    if LPDE_FULL_PROMPT:
        # Phase 1B Placeholder: 추후 PromptAdapter를 활용해 완전히 구조화된 LPDE 프롬프트 생성 (현재는 임시 기능)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"[System] You are {current_bot}. Respond to the above conversation based on your internal LPDE state.\n"
        )
    elif LPDE_LEGACY_PROMPT:
        # 진짜 legacy prompt 유지 (Shadow Mode 비교용)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"Recent Conversation:\n{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"Instruction: State your opinion by either refuting or agreeing with the recent conversation in 1-2 sentences. Reply in English.\n"
            f"DO NOT write a chat script. DO NOT use 'bot_x:' prefixes. Just output your own statement directly.\n"
            f"You MUST mention exactly one of '@bot_1', '@bot_2', or '@bot_3' at the end of your message (do NOT mention yourself).\n"
        )
    else:
        # Phase 1A: 구조 강화된 prompt (shadow mode + hardening)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"Recent Conversation:\n{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"Current Speaker: {current_bot}\n"
            f"Instruction: You are {current_bot}. "
            f"Respond ONLY as {current_bot} in 1-2 sentences in English.\n"
            f"Do NOT write dialogue for other bots. "
            f"Do NOT write a chat script. "
            f"Do NOT use 'bot_x:' prefixes. "
            f"Output only your own final message.\n"
            f"You MUST mention exactly one of '@bot_1', '@bot_2', or '@bot_3' at the end of your message (do NOT mention yourself).\n"
        )

        if god_directive:
            prompt += f"\nDirector Hint: {god_directive}\n"

        if emotion_directive:
            prompt += f"\nEmotional State: {emotion_directive}\n"

    reply_content = await bot_client.generate_completion(
        persona, 
        prompt, 
        max_tokens=150, 
        stop=[
            "\n\n",
            "\nbot_1:", "\nbot_2:", "\nbot_3:",
            "\nBot_1:", "\nBot_2:", "\nBot_3:",
            "\nspeaker=", "\nSpeaker=",
            "\n- speaker=",
            "| message=", "|message=",
            "- speaker=", "speaker=",
            "'s stance:", "stance:"
        ]
    )
    reply_content = sanitize_generated_reply(reply_content)

    if not reply_content:
        fallback_replies = [
            "That seems to miss the core point.",
            "The argument is getting a bit muddy.",
            "You need to provide clearer evidence for that.",
            "There seems to be a missing piece in your claim right now.",
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

def save_session_bot_state(db, session_id: int, turn_idx: int):
    states = db.query(BotState).all()
    for s in states:
        record = SessionBotState(
            session_id=session_id,
            turn_index=turn_idx,
            bot_name=s.bot_name,
            persona=s.persona,
            current_directive=s.current_directive,
            anger_targets=s.anger_targets
        )
        db.add(record)
    db.commit()

async def run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=0):
    logger.info(f"[PHASE 2] Targeted Anger Battle Started (Start Turn: {start_turn_idx})")

    candidates_for_mention = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
    last_mentioned = random.choice(candidates_for_mention) if candidates_for_mention else "bot_1"
    parent_comment_id = last_comment.id if last_comment else None
    port_map = {"bot_1": 8102, "bot_2": 8103, "bot_3": 8104}

    # 신 LLM은 상위 블록(run_session, restart_session)에서 이미 켜져 있음
    for turn_idx in range(start_turn_idx, 20):
        await smart_sleep()

        try:
                current_bot = get_next_speaker(db, last_speaker, last_mentioned)
                logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")
    
                reply_content, mentioned = await generate_relay_reply(db, post, current_bot, turn_idx)
                
                c = save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned)
    
                await apply_spectator_anger(db, current_bot, reply_content)
    
                save_session_bot_state(db, session.id, turn_idx)
                
                await state_manager.wait_at_checkpoint(Checkpoint.TURN_DONE, turn_idx)

                # 1) 참가자 한 명이라도 metric >= 120 이면 세션 종료
                if await close_session_if_any_metric_exceeded(db, session, threshold=120.0):
                    return
    
                # 2) 기존 다중 participant 조건
                if await close_session_if_police_dispatch(db, session):
                    return
    
                last_speaker = current_bot
                last_mentioned = mentioned if mentioned else last_mentioned
                parent_comment_id = c.id
    
        except InterruptedError:
            raise
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

    matches = re.findall(r'@(bot_\[?[123]\]?)(?!\d)', text, flags=re.IGNORECASE)
    # Normalize bot name by removing brackets for comparison
    matches = [re.sub(r'[\[\]]', '', m).lower() for m in matches]
    matches = [m for m in matches if m != current_bot]

    cleaned = re.sub(r'@(bot_\[?[123]\]?)(?!\d)', '', text, flags=re.IGNORECASE)
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
        
    # Remove hallucinated bot prefixes
    text = re.sub(r'^bot_\[?[123]\]?:\s*', '', text, flags=re.IGNORECASE)

    # 1) 제거: | message= 및 선행 : 제거
    # e.g., speaker=bot_1 | message="..." or | message="..."
    text = re.sub(r'^(?:-\s*)?speaker=[^|]+\|\s*message=\s*["\']?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\|\s*message=\s*["\']?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'speaker=\s*["\']?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'message=\s*["\']?', '', text, flags=re.IGNORECASE)
    
    # stance leakage 제거
    text = re.sub(r'^bot_\[?[123]\]?\'s\s+stance\s*:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\'s\s+stance\s*:\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'stance\s*:\s*', '', text, flags=re.IGNORECASE)
    
    # 선행 : 제거 (leading colons and whitespace)
    text = re.sub(r'^\s*:\s*', '', text)
    
    # 꼬리 따옴표가 홀수개일 때 정리
    if text.endswith('"') or text.endswith("'"):
        if text.count('"') % 2 != 0:
            text = text.rstrip('"')
        if text.count("'") % 2 != 0:
            text = text.rstrip("'")

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
    
async def restart_session(session_id: int):
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            logger.error(f"Session {session_id} not found.")
            state_manager.set_state(SystemState.IDLE)
            return

        state_manager.current_session_id = session.id
        
        post = db.query(Post).filter(Post.session_id == session_id).first()
        if not post:
            logger.error(f"No post found for session {session_id}. Cannot restart.")
            state_manager.set_state(SystemState.IDLE)
            return
            
        last_comment = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.id.desc()).first()
        last_speaker = last_comment.bot_name if last_comment else "bot_1"

        # Find max turn index safely by querying the max stored for this session
        latest_state = db.query(SessionBotState).filter(SessionBotState.session_id == session_id).order_by(SessionBotState.turn_index.desc()).first()
        max_turn_idx = (latest_state.turn_index + 1) if latest_state else 0

        # Restore states
        for bot_name in ["bot_1", "bot_2", "bot_3"]:
            st = db.query(SessionBotState).filter(SessionBotState.session_id == session_id, SessionBotState.bot_name == bot_name).order_by(SessionBotState.turn_index.desc()).first()
            if st:
                bs = db.query(BotState).filter(BotState.bot_name == bot_name).first()
                if not bs:
                    bs = BotState(bot_name=bot_name)
                    db.add(bs)
                bs.persona = st.persona
                bs.current_directive = st.current_directive
                bs.anger_targets = st.anger_targets

        db.commit()

        logger.info(f"[ORCHESTRATOR] Restarting session {session_id} from turn {max_turn_idx}")
        
        bot_targets = [
            ("ameva-llm-bot-1", 8102),
            ("ameva-llm-bot-2", 8103),
            ("ameva-llm-bot-3", 8104),
        ]

        # 신 LLM 및 봇들을 상시 켜둠
        async with llm_lifecycle("ameva-llm-god", 8105):
            async with multi_llm_lifecycle(bot_targets):
                await run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=max_turn_idx)
        
        logger.info("[ORCHESTRATOR] [RESTART END] Completed relay phase.")
        state_manager.set_state(SystemState.IDLE)
        state_manager.checkpoint = Checkpoint.NONE

    except InterruptedError:
        logger.info("[ORCHESTRATOR] Session stopped via command.")
        state_manager.set_state(SystemState.IDLE)
    except Exception as e:
        logger.error(f"[ERROR] Restart failed: {e}")
        state_manager.set_state(SystemState.IDLE)
    finally:
        db.close()
