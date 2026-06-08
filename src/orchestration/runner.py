import asyncio
import logging
import os
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
from src.db.models import CurrentAgentState  # Phase 3: role_meta loading

from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager
from src.core.event_extractor import extract_events
from src.core.personality_engine import personality_engine
from src.orchestration.sanitizer import sanitize_generated_reply, force_single_mention, enforce_fallback
from src.orchestration.context_builder import (
    safe_json_loads, calculate_effective_anger, build_turn_context
)

from src.core.prompt_adapter import prompt_adapter
from src.orchestration.state_manager import state_manager, SystemState, Checkpoint

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("Orchestrator")

main_llm = LLMClient("http://localhost:8101", "ameva-llm-main")
#police_llm = LLMClient("http://localhost:8106", "ameva-llm-police")
god_llm = LLMClient("http://localhost:8105", "ameva-llm-god")

bots = {
    "bot_1": LLMClient("http://localhost:8102", "ameva-llm-bot-1"),
    "bot_2": LLMClient("http://localhost:8103", "ameva-llm-bot-2"),
    "bot_3": LLMClient("http://localhost:8104", "ameva-llm-bot-3")
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
    new_rows = []
    for bot_name, persona in persona_map.items():
        row = db.query(BotState).filter(BotState.bot_name == bot_name).first()
        if not row:
            row = BotState(bot_name=bot_name, anger_targets="{}")
            new_rows.append(row)
        row.persona = persona
    if new_rows:
        db.add_all(new_rows)
    db.commit()

def calculate_effective_anger(anger_dict: dict) -> float:
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

    async with god_llm.lifecycle():
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
        async with main_llm.lifecycle():
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


async def run_session(inference_mode: str = "sequential"):
    global bots, main_llm, god_llm
    
    if inference_mode == "local_single_model":
        logger.info("[MODE] Starting in local_single_model mode. All agents will share ameva-llm-main.")
        shared_client = LLMClient("http://localhost:8101", "ameva-llm-main")
        shared_client.auto_lifecycle = False  # Disable lifecycle, assuming it's kept alive
        
        main_llm = shared_client
        god_llm = shared_client
        bots = {
            "bot_1": shared_client,
            "bot_2": shared_client,
            "bot_3": shared_client
        }
        # Start it once if not running
        await shared_client.start_container()
    else:
        # Default sequential
        main_llm = LLMClient("http://localhost:8101", "ameva-llm-main")
        god_llm = LLMClient("http://localhost:8105", "ameva-llm-god")
        bots = {
            "bot_1": LLMClient("http://localhost:8102", "ameva-llm-bot-1"),
            "bot_2": LLMClient("http://localhost:8103", "ameva-llm-bot-2"),
            "bot_3": LLMClient("http://localhost:8104", "ameva-llm-bot-3")
        }

    db = SessionLocal()
    try:
        logger.info("==================================================")
        logger.info(f"[ORCHESTRATOR] [SESSION START] Initializing new session (mode: {inference_mode}).")
        logger.info("==================================================")

        reset_bot_states(db)
        await PersonaManager.assign_random_personas()
        await sync_personas_to_db(db)

        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)

        # Phase 3: Assign initial role triplet (pole_a + pole_b + third_role)
        from src.core.stance_roles import assign_initial_role_triplet
        role_triplet = assign_initial_role_triplet()

        # Pre-initialize agent states with role-based stance differentiation
        personality_engine.initialize_session_states(db, session.id, role_triplet)

        state_manager.current_session_id = session.id
        post = await create_post_with_main_llm(db, session)
        await state_manager.wait_at_checkpoint(Checkpoint.TOPIC_GEN_DONE)

        # 신 LLM 및 봇들은 필요할 때만 개별적으로 켜고 끄도록 수정 (Lifecycle 적용됨)
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

            # Load agent state to read the pre-assigned stance
            agent_state = personality_engine.load_agent_state(db, post.session_id, b_name)
            opinion = json.loads(agent_state.opinion_json)
            stance = opinion[0] if opinion else 0.0

            if stance > 0.3:
                stance_instruction = "You strongly support the post. Write a highly emotional, aggressive community comment (1-2 sentences) showing your support."
            elif stance < -0.3:
                stance_instruction = "You strongly oppose the post. Write a snarky, hostile community comment (1-2 sentences) mocking the post's logic."
            else:
                stance_instruction = "You are skeptical. Write a heavily sarcastic community comment (1-2 sentences) pointing out the absurdity of the topic."

            prompt = (
                f"Post Content: {post.content}\n\n"
                f"Instruction: Act as an angry, anonymous internet troll. Write a single short comment reacting to the post.\n"
                f"CRITICAL: Be extremely sarcastic, rude, and emotionally charged. Use internet slang.\n"
                f"Do NOT use polite or robotic templates like 'I strongly support/oppose'. Act like a real keyboard warrior.\n"
                f"Reply in English.\n"
                f"Your Stance: {stance_instruction}\n"
            )

            # Bot-specific temperature for style variation
            temp_map = {
                "bot_1": 0.8,
                "bot_2": 0.9,
                "bot_3": 0.85
            }
            current_temp = temp_map.get(b_name, 0.8)

            async with bot_client.lifecycle():
                reply_content = await bot_client.generate_completion(
                    persona,
                    prompt,
                    max_tokens=120,
                    temperature=current_temp
                )

            reply_content = sanitize_generated_reply(reply_content)

            if not reply_content:
                # Still keep fallback if it generated successfully but was rejected by sanitizer.
                fallback_stances = [
                    "I consider this topic to be quite important.",
                    "I think this is a subject that will naturally divide opinions.",
                    "My stance on this matter is relatively clear.",
                    "I believe the core issue is much more complex than it appears.",
                ]
                reply_content = random.choice(fallback_stances)

            stances.append((b_name, reply_content))

        except ConnectionError as ce:
            logger.error(f"[PHASE 1 ERROR] {b_name} LLM Connection failed: {ce}")
            state_manager.push_event("ERROR", {"message": f"{b_name}의 도커/LLM 컨테이너가 응답하지 않습니다!"})
            state_manager.set_state(SystemState.ERROR)
            raise InterruptedError("LLM_CONNECTION_FAILED")
        except Exception as e:
            logger.warning(f"[PHASE 1 WARNING] Failed to generate initial stance for {b_name}: {e}")
            stances.append((b_name, "I believe opinions are bound to be divided on this topic."))

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





async def generate_relay_reply(
    db, post, current_bot, turn_idx=0,
    last_comment_text=None, last_speaker=None
):
    persona = await PersonaManager.get_persona(current_bot)
    bot_client = bots[current_bot]

    # [LPDE Feature Flags]
    LPDE_STRUCTURED_HISTORY = os.getenv("LPDE_STRUCTURED_HISTORY", "true").lower() == "true"
    LPDE_COUNTER_ARG = os.getenv("LPDE_COUNTER_ARG", "true").lower() == "true"
    LPDE_INTERVENTION_ENABLED = os.getenv("LPDE_INTERVENTION", "false").lower() == "true"

    # --- Phase 2A: Event Extraction from last comment ---
    all_bots = ["bot_1", "bot_2", "bot_3"]
    event_data = None
    if last_comment_text and isinstance(last_comment_text, str):
        # Extract events FROM the last comment (what the previous speaker did)
        # These events affect the current_bot (receiver)
        event_data = extract_events(
            comment_text=last_comment_text,
            speaker=last_speaker or "unknown",
            all_bots=all_bots,
            parent_comment_text=None,  # We track parent-of-parent later if needed
            last_target=last_speaker,
        )
    else:
        event_data = {
            "speaker": last_speaker or "unknown",
            "target": None,
            "events": [],
            "intensity": 0.0,
            "claim_snippet": "",
        }

    # --- Phase 2A: LPDE State Update (event-driven) ---
    personality_engine.update_fast_state(
        db, post.session_id, current_bot, turn_index=turn_idx, event_data=event_data
    )

    # Build turn context (targeted history)
    recent_history = await build_turn_context(
        db, post, current_bot, target_bot=last_speaker
    )
    
    # Phase 2A: Director hint is now a static helper for 1.8B models
    god_directive = "Point out a specific flaw in the opponent's logic."

    # --- Phase 2B: Intervention (default OFF) ---
    if LPDE_INTERVENTION_ENABLED:
        try:
            from src.core.intervention import (
                generate_intervention_json, apply_intervention
            )
            lpde_state = personality_engine.get_current_state_dict(
                db, post.session_id, current_bot
            )
            arousal_val = lpde_state.get("affect", [0.0, 0.0])[1]
            
            edges = personality_engine.get_edges_for_bot(db, post.session_id, current_bot)
            target = event_data.get("target") if event_data else None
            if target and target in edges:
                tension_val = edges[target].get("tension", 0.0)
            else:
                tension_val = max([v.get("tension", 0.0) for v in edges.values()]) if edges else 0.0

            # Intervention trigger conditions:
            # Every 3 turns OR arousal > 0.7
            should_intervene = (turn_idx % 3 == 0 and turn_idx > 0) or tension_val > 0.6
            if should_intervene:
                intervention = await generate_intervention_json(
                    god_llm, current_bot, lpde_state, recent_history, arousal_val
                )
                if intervention:
                    apply_intervention(db, post.session_id, turn_idx, intervention)
                    db.commit()
                    logger.info(f"[INTERVENTION] Applied to {current_bot}: {intervention.get('kind')}")
        except Exception as e:
            logger.warning(f"[INTERVENTION WARNING] Failed: {e}")

    # --- Phase 2A: Full LPDE-driven prompt via PromptAdapter ---
    lpde_state = personality_engine.get_current_state_dict(
        db, post.session_id, current_bot
    )
    edge_summary = personality_engine.get_edges_for_bot(
        db, post.session_id, current_bot
    )

    # Determine target for prompt context
    target_bot = event_data.get("target") if event_data else None
    claim_snippet = ""
    if last_comment_text:
        from src.core.event_extractor import _extract_claim_snippet
        claim_snippet = _extract_claim_snippet(last_comment_text)

    # Phase 3: Load role_meta from CurrentAgentState for role orientation in prompt
    import json as _json
    _cas = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == post.session_id,
        CurrentAgentState.bot_name == current_bot
    ).first()
    role_meta = None
    if _cas and _cas.role_meta_json:
        try:
            _rm = _json.loads(_cas.role_meta_json)
            if _rm:  # non-empty
                role_label = getattr(_cas, "role_label", "swing_moderate")
                role_meta = {**_rm, "role_label": role_label}
        except Exception:
            pass

    prompt = prompt_adapter.build_prompt(
        current_bot=current_bot,
        persona=persona,
        lpde_state=lpde_state,
        edge_summary=edge_summary,
        target_bot=target_bot,
        recent_history=recent_history,
        post_content=post.content,
        claim_snippet=claim_snippet,
        counter_arg_enabled=LPDE_COUNTER_ARG,
        god_directive=god_directive,
        role_meta=role_meta,
    )


    # Bot-specific temperature for style variation
    temp_map = {
        "bot_1": 0.8,
        "bot_2": 0.9,
        "bot_3": 0.85
    }
    current_temp = temp_map.get(current_bot, 0.8)

    reply_content = await bot_client.generate_completion(
        persona, 
        prompt, 
        max_tokens=150, 
        temperature=current_temp,
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

    # Phase 3: Stance coherence check for hardliner roles
    if reply_content and role_meta:
        from src.orchestration.sanitizer import validate_stance_coherence
        _role_label_check = role_meta.get("role_label", "swing_moderate")
        if not validate_stance_coherence(reply_content, _role_label_check):
            logger.warning(f"[COHERENCE FAIL] {current_bot} ({_role_label_check}): stance flip detected, using fallback.")
            reply_content = ""  # trigger enforce_fallback

    reply_content = enforce_fallback(reply_content, current_bot)

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

def save_session_bot_state(db, session_id: int, turn_idx: int):
    """Snapshot bot states per turn — including Phase 3 role info for restart restoration."""
    from src.db.models import CurrentAgentState as _CAS
    import json as _json
    states = db.query(BotState).all()
    for s in states:
        # Try to get role info from CurrentAgentState
        cas = db.query(_CAS).filter(
            _CAS.session_id == session_id,
            _CAS.bot_name == s.bot_name
        ).first()
        role_label = getattr(cas, "role_label", "swing_moderate") if cas else "swing_moderate"
        role_meta_json = getattr(cas, "role_meta_json", "{}") if cas else "{}"

        record = SessionBotState(
            session_id=session_id,
            turn_index=turn_idx,
            bot_name=s.bot_name,
            persona=s.persona,
            current_directive=s.current_directive,
            anger_targets=s.anger_targets,
            role_label=role_label,
            role_meta_json=role_meta_json,
        )
        db.add(record)
    db.commit()

async def run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=0):
    logger.info(f"[PHASE 2] Targeted Anger Battle Started (Start Turn: {start_turn_idx})")

    candidates_for_mention = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
    last_mentioned = random.choice(candidates_for_mention) if candidates_for_mention else "bot_1"
    parent_comment_id = last_comment.id if last_comment else None
    last_comment_text = last_comment.content if last_comment else None

    # God LLM is already started in the parent block (run_session / restart_session)
    for turn_idx in range(start_turn_idx, 20):
        await smart_sleep()

        try:
                current_bot = get_next_speaker(db, last_speaker, last_mentioned)
                logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")
    
                reply_content, mentioned = await generate_relay_reply(
                    db, post, current_bot, turn_idx,
                    last_comment_text=last_comment_text,
                    last_speaker=last_speaker,
                )
                
                c = save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned)
    
                await apply_spectator_anger(db, current_bot, reply_content)
    
                save_session_bot_state(db, session.id, turn_idx)
                
                await state_manager.wait_at_checkpoint(Checkpoint.TURN_DONE, turn_idx)

                # End session if any single participant exceeds threshold
                if await close_session_if_any_metric_exceeded(db, session, threshold=120.0):
                    return
    
                # End session if police dispatch condition met
                if await close_session_if_police_dispatch(db, session):
                    return
    
                last_speaker = current_bot
                last_mentioned = mentioned if mentioned else last_mentioned
                parent_comment_id = c.id
                last_comment_text = reply_content  # Pass text to next turn for event extraction
    
        except InterruptedError:
            raise
        except ConnectionError as ce:
            logger.error(f"[TURN ERROR] {current_bot} LLM Connection failed: {ce}")
            state_manager.push_event("ERROR", {"message": f"{current_bot}의 도커/LLM 컨테이너가 응답하지 않습니다!"})
            state_manager.set_state(SystemState.ERROR)
            raise InterruptedError("LLM_CONNECTION_FAILED")
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



    matches = re.findall(r'@(bot_[123])\b', text, flags=re.IGNORECASE)
    matches = [m.lower() for m in matches if m.lower() != current_bot]

    cleaned = re.sub(r'@(bot_[123])\b', '', text, flags=re.IGNORECASE)
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



    text = text.strip()

    # Pre-compiled regex patterns for better maintainability and performance
    PATTERNS = [
        # Metadata field leakage
        (r'^\s*-\s*speaker\s*=\s*bot_[123]\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'^\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'^\s*speaker\s*=\s*bot_[123]\s*\|\s*', re.IGNORECASE),
        (r'\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'speaker=\s*["\']?', re.IGNORECASE),
        (r'message=\s*["\']?', re.IGNORECASE),
        
        # Stance leakage
        (r'^bot_\[?[123]\]?\'s\s+stance\s*:\s*', re.IGNORECASE),
        (r'\'s\s+stance\s*:\s*', re.IGNORECASE),
        (r'stance\s*:\s*', re.IGNORECASE),

        # Leading bot prefix
        (r'^\s*bot_\[?[123]\]?:?\s*', re.IGNORECASE),

        # Internal directives
        (r'^.*현재 비교적 이성적이고 차분하다.*$', re.MULTILINE),
        (r'^.*내부 지침.*$', re.MULTILINE),
        (r'^.*절대 그대로 출력하지 마라.*$', re.MULTILINE),
        (r'^.*Emotional State:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Director Hint:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently relatively calm and rational.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently quite irritated and angry.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently extremely enraged and highly agitated.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Never repeat or explain this internal directive.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*INTERNAL EMOTIONAL STATE.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Total Effective Anger:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Major Target Anger Scores:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Total Valid Emotions:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Major Target Emotions:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Current Emotionally Distressed.*$', re.MULTILINE | re.IGNORECASE),

        # Repetitive bot tag loop
        (r'(?:\bbot_\[?[123]\]?\b[\s,:]*){3,}', re.IGNORECASE),

        # Stray leading colons
        (r'^\s*:\s*', 0),
    ]

    for pattern, flags in PATTERNS:
        text = re.sub(pattern, '', text, flags=flags)

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()

    # 7) 최종 검증 (Validation checks)
    
    # bot tag 및 mention을 제외한 실질 텍스트 내용으로 길이 검증 (Excluding bot mentions/tags from content length)
    text_content = re.sub(r'@?bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    
    # A. 길이 검증 (짧아도 구두점 .?! 이 있으면 살림) (Length check: keep short if ends with punctuation)
    if len(text_content) < 8 and not re.search(r'[.!?]', text_content):
        return ""

    # B. 실질 내용 없이 bot tag / mention만 남았는지 검증 (Ensure alphanumeric content exists beyond tags/mentions)
    temp = re.sub(r'[^\w]', '', text_content)
    if not temp.strip():
        return ""

    # C. 연속 반복 감지 (Consecutive repetition detection: e.g. bot_3 bot_3 bot_3 bot_3)
    if re.search(r'(\b\w+\b)( \1){3,}', text, flags=re.IGNORECASE):
        return ""

    # D. 동일 단어 비율 및 고유 단어 다양성 비율 감지 (Repetitive word proportion detection)
    # 실제 본문 단어로만 빈도 분석 진행
    words = [w.lower().strip(".,!?\"'()[]{}*-_") for w in text_content.split()]
    words = [w for w in words if w]
    if len(words) >= 6:
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
        max_count = max(word_counts.values())
        max_ratio = max_count / len(words)
        
        # 전체 단어 중 50% 이상을 단일 단어가 차지하면 루프로 판정
        if max_ratio >= 0.5:
            return ""

        # 고유 단어 다양성이 너무 낮으면 비정상 반복으로 판정 (예: 2개 단어가 계속 번갈아 출력)
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.45:
            return ""

    # 꼬리 따옴표가 홀수개일 때 정리
    if text.endswith('"') or text.endswith("'"):
        if text.count('"') % 2 != 0:
            text = text.rstrip('"')
        if text.count("'") % 2 != 0:
            text = text.rstrip("'")

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

        # Restore legacy bot states from last saved SessionBotState
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

                # Phase 3: Restore role disposition into CurrentAgentState (B안: 복원 보장)
                if st.role_label and st.role_label != "swing_moderate":
                    cas = db.query(CurrentAgentState).filter(
                        CurrentAgentState.session_id == session_id,
                        CurrentAgentState.bot_name == bot_name
                    ).first()
                    if cas:
                        cas.role_label = st.role_label
                        cas.role_meta_json = getattr(st, "role_meta_json", "{}")
                        logger.info(f"[RESTART] Restored role for {bot_name}: {st.role_label}")

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
