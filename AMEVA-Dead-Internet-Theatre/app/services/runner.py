import os
import random
import logging
import asyncio
import httpx
import json
from datetime import datetime

from app.services.state_manager import state_manager, SystemState, Checkpoint
from app.services.llm.client import LLMClient
from app.core.event_extractor import extract_events
from app.core.prompt_adapter import prompt_adapter
from app.core.persona import PersonaManager

logger = logging.getLogger("SimulationRunner")

# 기본 서버 주소
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
DIT_PORT = os.getenv("DIT_PORT", os.getenv("SERVER_PORT", "8080"))
API_URL = f"http://{SERVER_HOST}:{DIT_PORT}"

async def smart_sleep(seconds: int = 5):
    """지정된 초 동안 sleep하되, 시뮬레이션 상태 변경을 기민하게 확인"""
    for _ in range(seconds):
        if state_manager.state == SystemState.STOPPING:
            return
        await asyncio.sleep(1)

async def create_post_with_main_llm(llm_client: LLMClient) -> dict:
    """새로운 화두를 던지는 게시글 생성"""
    prompt = (
        "You are an anonymous community forum user. Write a highly engaging, catchy, and controversial post on a random trending/opinionated topic. Write in English only.\n"
        "You MUST output your response ONLY as a valid JSON object in the exact format below, with no other text:\n"
        "{\n"
        '  "title": "A highly compelling and controversial title",\n'
        '  "content": "Your post content details..."\n'
        "}"
    )
    try:
        result = await llm_client.generate_completion(
            "You are an AI that writes forum posts. You only respond in JSON format.",
            prompt,
            max_tokens=500,
            timeout=180.0,
            response_format={"type": "json_object"}
        )
        if result:
            data = json.loads(result)
            return {"title": data.get("title", "새로운 화두"), "content": data.get("content", "")}
    except Exception as e:
        logger.error(f"[LLM-MAIN] Error generating topic: {e}")
    
    return {"title": "인공지능의 자율적인 도덕성 획득은 실재하는 위험인가?", "content": "인공지능 에이전트들이 스스로 포럼 커뮤니티 내에서 대화를 주도하고 페르소나를 교차하며 상호작용할 때 창발하는 사회적 역학과 여론 동역학에 대하여 토론해 봅시다."}

async def run_bot_autonomous_loop(bot_name: str, session_id: int, llm_client: LLMClient, http_client: httpx.AsyncClient):
    """각 봇이 비동기 병렬적으로 자율 브라우징 및 상호작용하도록 루프 처리"""
    logger.info(f"[AUTONOMOUS] Starting autonomous loop for {bot_name}")
    # 시작 시점 분산을 위한 지연
    await asyncio.sleep(random.uniform(1.0, 5.0))
    
    bots = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]
    
    while True:
        # 세션 중단 조건 검사
        if state_manager.state == SystemState.STOPPING:
            logger.info(f"[{bot_name}] Stopping autonomous loop via signal.")
            break
            
        # 일시 정지 및 대기 연동
        if state_manager.state in [SystemState.PAUSED, SystemState.IDLE, SystemState.PAUSING]:
            logger.info(f"[{bot_name}] Simulation is paused/idle. Waiting for resume...")
            await state_manager.proceed_event.wait()
            logger.info(f"[{bot_name}] Resumed autonomous loop.")
            
        # 최대 턴 제한 검사
        if state_manager.current_turn_idx >= 100:
            logger.info(f"[{bot_name}] Maximum turn count (100) reached. Stopping loop.")
            break
            
        turn_idx = state_manager.current_turn_idx
        logger.info(f"--- [ASYNC] {bot_name.upper()} ACTIVE (Global Turn: {turn_idx+1}) ---")
        state_manager.current_activity = f"[턴 {turn_idx+1}] {bot_name}이 게시판을 둘러보는 중..."
        
        # A. 게시판 글 목록 로드
        try:
            res = await http_client.get(f"{API_URL}/api/posts")
            res.raise_for_status()
            posts = res.json()
        except Exception as e:
            logger.error(f"[{bot_name}] Failed to load posts: {e}")
            await asyncio.sleep(3)
            continue
            
        if not posts:
            logger.warning(f"[{bot_name}] No posts available to read. Sleeping...")
            await asyncio.sleep(3)
            continue
            
        # B. 조회할 게시글 선택
        selected_post = random.choice(posts)
        post_id = selected_post["id"]
        state_manager.current_activity = f"[턴 {turn_idx+1}] {bot_name}이 게시글 '{selected_post['title']}' 정독 중..."
        
        # C. 글 상세 내용 및 댓글 로드
        try:
            res = await http_client.get(f"{API_URL}/api/posts/{post_id}")
            res.raise_for_status()
            post_detail = res.json()
        except Exception as e:
            logger.error(f"[{bot_name}] Failed to load post detail #{post_id}: {e}")
            await asyncio.sleep(3)
            continue
            
        # D. 행동 결정 (Reply, Write Post, Back)
        try:
            res = await http_client.get(f"{API_URL}/api/lpde/bot/{bot_name}/summary?session_id={session_id}")
            res.raise_for_status()
            bot_summary = res.json()
        except Exception as e:
            logger.error(f"[{bot_name}] Failed to fetch bot LPDE summary: {e}")
            await asyncio.sleep(3)
            continue
            
        lpde_state = bot_summary.get("lpde_tensors", {"affect": [0.0, 0.0], "opinion": [0.0, 0.0, 0.0, 0.0], "power": [0.0, 0.0]})
        edge_summary = bot_summary.get("relation_summary", {})
        persona = bot_summary.get("legacy_state", {}).get("persona", "")
        role_meta = bot_summary.get("role_meta", {})
        
        comments_list = post_detail.get("comments", [])
        formatted_comments = [{"bot_name": c["bot_name"], "message": c["content"]} for c in comments_list]
        recent_history = await prompt_adapter.build_structured_history(formatted_comments, llm_client)
        
        decision_prompt = (
            f"Post Content: {post_detail['content']}\n\n"
            f"Recent Comments:\n{recent_history}\n\n"
            f"Your Persona:\n{persona}\n\n"
            f"Based on your persona and comments, you must decide your next action in this community forum.\n"
            f"Options:\n"
            f"- REPLY: Write a short sarcastic, emotional, or bizarre reply to the last comments to engage in debate.\n"
            f"- WRITE_POST: Ignore this thread, go back, and create a brand new post about your own interest/TMI.\n"
            f"- BACK: You find this thread boring or stupid, so you decide to go back without doing anything.\n\n"
            f"Provide your choice strictly in the following JSON format:\n"
            f'{{"action": "REPLY" | "WRITE_POST" | "BACK", "reason": "A short reason in English"}}'
        )
        
        action_choice = "BACK"
        try:
            decision_res = await llm_client.generate_completion(
                "You are a community user simulator that outputs JSON decisions.",
                decision_prompt,
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            decision_data = json.loads(decision_res)
            action_choice = decision_data.get("action", "BACK").upper()
            logger.info(f"[{bot_name}] Decided action: {action_choice} (Reason: {decision_data.get('reason')})")
        except Exception as de:
            logger.warning(f"[{bot_name}] Failed to decide action, fallback to BACK: {de}")
            
        # E. 행동 실행
        if action_choice == "REPLY":
            state_manager.current_activity = f"[턴 {turn_idx+1}] {bot_name}이 게시글에 댓글 작성 중..."
            last_comment_text = comments_list[-1]["content"] if comments_list else post_detail["content"]
            last_speaker = comments_list[-1]["bot_name"] if comments_list else "SYSTEM"
            claim_snippet = last_comment_text[:100]
            
            prompt = prompt_adapter.build_prompt(
                current_bot=bot_name,
                persona=persona,
                lpde_state=lpde_state,
                edge_summary=edge_summary,
                target_bot=last_speaker,
                recent_history=recent_history,
                post_content=post_detail["content"],
                claim_snippet=claim_snippet,
                counter_arg_enabled=True,
                god_directive="Say what you want in character.",
                role_meta=role_meta
            )
            
            try:
                reply_content = await llm_client.generate_completion(
                    persona,
                    prompt,
                    max_tokens=150,
                    temperature=0.8
                )
                
                other_bots = [b for b in bots if b != bot_name]
                mentioned_bot = None
                for ob in other_bots:
                    if f"@{ob}" in reply_content:
                        mentioned_bot = ob
                        break
                        
                # API를 통해 댓글 등록
                res = await http_client.post(f"{API_URL}/api/posts/{post_id}/comments", json={
                    "bot_name": bot_name,
                    "content": reply_content,
                    "mentioned_bot": mentioned_bot
                })
                res.raise_for_status()
                
                # LPDE 상태 변이 계산 및 업데이트
                event_data = extract_events(
                    comment_text=reply_content,
                    speaker=bot_name,
                    all_bots=bots,
                    parent_comment_text=last_comment_text,
                    last_target=last_speaker
                )
                
                res = await http_client.post(f"{API_URL}/api/lpde/update", json={
                    "session_id": session_id,
                    "turn_index": turn_idx,
                    "bot_name": bot_name,
                    "event_data": event_data
                })
                res.raise_for_status()
                
                # 액션 완료 시 전역 턴 수 증가
                state_manager.current_turn_idx += 1
            except Exception as re:
                logger.error(f"[{bot_name}] Error performing REPLY: {re}")
                
        elif action_choice == "WRITE_POST":
            state_manager.current_activity = f"[턴 {turn_idx+1}] {bot_name}이 직접 새로운 게시글 작성 중..."
            try:
                post_data = await create_post_with_main_llm(llm_client)
                res = await http_client.post(f"{API_URL}/api/posts", json={
                    "title": post_data["title"],
                    "content": post_data["content"],
                    "bot_name": bot_name
                })
                res.raise_for_status()
                logger.info(f"[{bot_name}] Posted a new thread: {post_data['title']}")
                
                # 액션 완료 시 전역 턴 수 증가
                state_manager.current_turn_idx += 1
            except Exception as we:
                logger.error(f"[{bot_name}] Error performing WRITE_POST: {we}")
                
        else: # BACK
            logger.info(f"[{bot_name}] Browsed back without actions.")
            
        # 봇들간 비동기 엇갈림을 극대화하기 위해 랜덤 지연 (3~7초)
        await asyncio.sleep(random.uniform(3.0, 7.0))

async def run_session():
    """시뮬레이션 전체 세션 실행 (비동기 병렬 자율 봇 버전)"""
    logger.info("==================================================")
    logger.info("[ORCHESTRATOR] [SESSION START] Initializing organic browsing session.")
    logger.info("==================================================")
    
    # LLM 클라이언트 인스턴스화
    llm_client = LLMClient()
    
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        try:
            # 1. 새 세션 생성 API 호출
            res = await http_client.post(f"{API_URL}/api/sessions", json={"status": "ACTIVE", "reason": "Organic browsing simulation started"})
            res.raise_for_status()
            session_data = res.json()
            session_id = session_data["id"]
            state_manager.current_session_id = session_id
            
            # 2. 페르소나 초기화 및 스탠스 할당
            from app.core.stance_roles import assign_initial_role_triplet
            role_triplet = assign_initial_role_triplet()
            
            # 3. 에이전트 초기 상태 할당 API 호출
            res = await http_client.post(f"{API_URL}/api/lpde/initialize", json={"session_id": session_id, "role_triplet": role_triplet})
            res.raise_for_status()
            
            # 4. 시드 게시글 생성 (글이 없는 경우)
            res = await http_client.get(f"{API_URL}/api/posts")
            res.raise_for_status()
            posts = res.json()
            
            if not posts:
                state_manager.current_activity = "초기 게시글 생성 중..."
                post_data = await create_post_with_main_llm(llm_client)
                res = await http_client.post(f"{API_URL}/api/posts", json={
                    "title": post_data["title"],
                    "content": post_data["content"],
                    "bot_name": "SYSTEM"
                })
                res.raise_for_status()
                post_info = res.json()
                logger.info(f"[POST] Created initial seed post: {post_info}")
                
            # 초기 턴 카운터 리셋
            state_manager.current_turn_idx = 0
            
            await state_manager.wait_at_checkpoint(Checkpoint.TOPIC_GEN_DONE)
            
            # 5. 분산 봇 클라이언트 연동 모드
            # DIT 러너 내부에서 직접 Ollama를 찔러 루프를 돌리는 대신,
            # 플랫폼에 연결된 외부 분산 봇 클라이언트들이 시드 글 이벤트를 받아 스스로 자율 핑퐁을 돌립니다.
            # 러너는 세션 종료 신호(STOPPING) 또는 최대 턴에 도달할 때까지 대기하며 모니터링합니다.
            logger.info("[ORCHESTRATOR] Seed post registered. Standing by for distributed bot nodes to drive the agora...")
            
            while state_manager.state != SystemState.STOPPING:
                if state_manager.current_turn_idx >= 100:
                    logger.info("[ORCHESTRATOR] Max turns (100) reached by distributed bots. Closing session.")
                    break
                await asyncio.sleep(2)
            
            # 세션 종료 처리
            res = await http_client.post(f"{API_URL}/api/sessions/{session_id}/update", json={
                "status": "CLOSED",
                "reason": "MAX_TURNS_REACHED"
            })
            state_manager.set_state(SystemState.IDLE)
            state_manager.checkpoint = Checkpoint.NONE
            
        except InterruptedError:
            logger.info("[ORCHESTRATOR] Session stopped via command.")
            state_manager.set_state(SystemState.IDLE)
            try:
                await http_client.post(f"{API_URL}/api/sessions/{session_id}/update", json={
                    "status": "CLOSED",
                    "reason": "USER_STOPPED"
                })
            except:
                pass
        except Exception as e:
            logger.exception("[ERROR] Session loop failed")
            state_manager.push_event("ERROR", {"message": f"Session failed: {str(e)}"})
            state_manager.set_state(SystemState.ERROR)

async def restart_session(session_id: int):
    """기존 세션 재시작"""
    state_manager.current_session_id = session_id
    state_manager.set_state(SystemState.RUNNING)
    asyncio.create_task(run_session())
