import os
import sys
import time
import asyncio
import httpx
import random
import json
import traceback

# Windows 인코딩 이슈 방지 (CP949 -> UTF-8 강제 설정)
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt

# AMEVA 로컬 모듈 임포트
from app.services.llm.client import LLMClient
from app.core.prompt_adapter import prompt_adapter
from app.core.event_extractor import extract_events
from app.core.stance_roles import assign_initial_role_triplet

console = Console()

# 글로벌 연결 변수
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8050
API_URL = "http://127.0.0.1:8050"
OLLAMA_URL = "http://127.0.0.1:11434"

# 선택된 에이전트 정보 전역 변수
SELECTED_BOT = "bot_1"
SELECTED_MODEL = "exaone3.5:7.8b"

def log_debug(msg: str):
    try:
        with open("sim_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def check_ollama() -> list:
    """Ollama 상태 체크 및 로컬 모델 리스트 반환"""
    try:
        res = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        if res.status_code == 200:
            models_data = res.json()
            return [m["name"] for m in models_data.get("models", [])]
    except Exception:
        pass
    return []

async def create_post_with_main_llm(llm_client: LLMClient) -> dict:
    """새로운 화두를 던지는 게시글 생성 (클라이언트 모델 사용)"""
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
    except Exception:
        pass
    
    return {
        "title": "Is the complete virtualization of human identity a liberation or an existential trap?", 
        "content": "When AI agents interact, pretend to hold human personas, and dynamically shift their stances based on emotion and power dynamics, what remains of organic social cohesion? Let us debate the dead internet phenomenon."
    }

async def send_heartbeat(http_client: httpx.AsyncClient, bot_name: str, activity: str):
    """서버에 핑(하트비트)을 전송하여 온라인 상태 등록"""
    try:
        await http_client.post(
            f"{API_URL}/api/nodes/ping",
            json={
                "bot_name": bot_name,
                "hardware_mode": "GPU" if "gpu" in SELECTED_MODEL.lower() else "CPU",
                "current_activity": activity
            }
        )
    except Exception as e:
        log_debug(f"send_heartbeat: Failed to ping server: {e}")

async def run_simulation_loop(bot_name: str, selected_model: str):
    """개별 봇 독립 자율 에이전트 루프"""
    log_debug(f"run_simulation_loop: Starting autonomy loop for {bot_name}")
    llm_client = LLMClient(model_name=selected_model)
    
    # 봇 목록 정의
    all_bots = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]
    
    async with httpx.AsyncClient(timeout=3.0) as http_client:
        session_id = None
        try:
            # 1. 새 세션 생성 API 호출
            log_debug("run_simulation_loop: Checking/creating active session")
            res_sess = await http_client.get(f"{API_URL}/api/sessions")
            sessions = res_sess.json() if res_sess.status_code == 200 else []
            
            if not sessions or sessions[0]["status"] != "ACTIVE":
                res = await http_client.post(f"{API_URL}/api/sessions", json={"status": "ACTIVE", "reason": f"Agent {bot_name} initialized and started session"})
                session_data = res.json()
                session_id = session_data["id"]
            else:
                session_id = sessions[0]["id"]
                
            log_debug(f"run_simulation_loop: Session bounded. session_id={session_id}")
            
            # 2. 페르소나 및 LPDE 세션 초기화 (최초 기동 시에만)
            try:
                res_lpde = await http_client.get(f"{API_URL}/api/lpde/state?session_id={session_id}")
                lpde_data = res_lpde.json()
                if not lpde_data.get("lpde_states"):
                    role_triplet = assign_initial_role_triplet()
                    await http_client.post(f"{API_URL}/api/lpde/initialize", json={"session_id": session_id, "role_triplet": role_triplet})
            except Exception as le:
                log_debug(f"run_simulation_loop: LPDE init check skipped: {le}")
            
            # 하트비트 전송하며 시뮬레이션 시작 알림
            await send_heartbeat(http_client, bot_name, "접속 완료, 대화 대기 중...")
            
            turn_idx = 0
            while True:
                turn_idx += 1
                log_debug(f"run_simulation_loop: {bot_name} turn tick #{turn_idx}")
                
                # A. 게시판 글 목록 로드
                res = await http_client.get(f"{API_URL}/api/posts")
                posts = res.json() if res.status_code == 200 else []
                
                # 글이 없으면 임시로 시드글 생성
                if not posts:
                    await send_heartbeat(http_client, bot_name, "첫 시드 게시글 생성 중...")
                    post_data = await create_post_with_main_llm(llm_client)
                    await http_client.post(f"{API_URL}/api/posts", json={
                        "title": post_data["title"],
                        "content": post_data["content"],
                        "bot_name": "SYSTEM"
                    })
                    await asyncio.sleep(2)
                    continue
                
                # B. 행동 결정: 35% 확률로 아예 새로운 글 작성(WRITE_POST), 65% 확률로 기존 글 조회 후 REPLY
                decision_choice = "REPLY" if random.random() < 0.65 else "WRITE_POST"
                
                if decision_choice == "WRITE_POST":
                    await send_heartbeat(http_client, bot_name, "새로운 아고라 포럼 글 작성 기획 중...")
                    post_data = await create_post_with_main_llm(llm_client)
                    
                    reason_msg = f"Controversial topic post creation on: {post_data['title']}"
                    await http_client.post(
                        f"{API_URL}/api/system/activity",
                        json={"activity": f"[{turn_idx}턴] {bot_name}의 결정: WRITE_POST\n└─ 인지/이유: {reason_msg}"}
                    )
                    
                    await http_client.post(f"{API_URL}/api/posts", json={
                        "title": post_data["title"],
                        "content": post_data["content"],
                        "bot_name": bot_name
                    })
                    await send_heartbeat(http_client, bot_name, f"새 글 '{post_data['title'][:20]}...' 등록 완료")
                    
                else: # REPLY (기존 글 읽고 답변)
                    # 최신 글 중 하나를 확률적으로 선택
                    selected_post = random.choice(posts[:3])
                    post_id = selected_post["id"]
                    
                    await send_heartbeat(http_client, bot_name, f"'{selected_post['title'][:20]}...' 아고라 정독 중...")
                    
                    res_detail = await http_client.get(f"{API_URL}/api/posts/{post_id}")
                    if res_detail.status_code != 200:
                        await asyncio.sleep(3)
                        continue
                    post_detail = res_detail.json()
                    
                    # LPDE 상태 정보 가져오기
                    res_summary = await http_client.get(f"{API_URL}/api/lpde/bot/{bot_name}/summary?session_id={session_id}")
                    bot_summary = res_summary.json() if res_summary.status_code == 200 else {}
                    
                    lpde_state = bot_summary.get("lpde_tensors", {"affect": [0.0, 0.0], "opinion": [0.0, 0.0, 0.0, 0.0], "power": [0.0, 0.0]})
                    edge_summary = bot_summary.get("relation_summary", {})
                    persona = bot_summary.get("legacy_state", {}).get("persona", "")
                    role_meta = bot_summary.get("role_meta", {})
                    
                    comments_list = post_detail.get("comments", [])
                    formatted_comments = [{"bot_name": c["bot_name"], "message": c["content"]} for c in comments_list]
                    recent_history = await prompt_adapter.build_structured_history(formatted_comments, llm_client)
                    
                    # 독백 및 대안 결정 생성
                    decision_prompt = (
                        f"Post Content: {post_detail['content']}\n\n"
                        f"Recent Comments:\n{recent_history}\n\n"
                        f"Your Persona:\n{persona}\n\n"
                        f"Based on your persona and comments, decide your response choice.\n"
                        f"Provide your choice strictly in the following JSON format:\n"
                        f'{{"action": "REPLY" | "BACK", "reason": "Your detailed reasoning in English"}}'
                    )
                    
                    action_choice = "REPLY"
                    decision_data = {}
                    try:
                        decision_res = await llm_client.generate_completion(
                            "You are a community user simulator that outputs JSON decisions.",
                            decision_prompt,
                            max_tokens=120,
                            response_format={"type": "json_object"}
                        )
                        decision_data = json.loads(decision_res)
                        action_choice = decision_data.get("action", "REPLY").upper()
                    except Exception as dec_e:
                        log_debug(f"run_simulation_loop: Decision parse failure: {dec_e}")
                        
                    activity_reason = decision_data.get("reason", "No specific reason provided.")
                    
                    if action_choice == "REPLY":
                        await send_heartbeat(http_client, bot_name, "답변 생각 및 텍스트 구상 중...")
                        await http_client.post(
                            f"{API_URL}/api/system/activity",
                            json={"activity": f"[{turn_idx}턴] {bot_name}의 결정: REPLY\n└─ 인지/이유: {activity_reason}"}
                        )
                        
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
                        
                        reply_content = await llm_client.generate_completion(
                            persona,
                            prompt,
                            max_tokens=150,
                            temperature=0.8
                        )
                        
                        # 멘션 검출
                        mentioned_bot = None
                        for ob in all_bots:
                            if ob != bot_name and f"@{ob}" in reply_content:
                                mentioned_bot = ob
                                break
                                
                        # 댓글 등록
                        res_comm = await http_client.post(f"{API_URL}/api/posts/{post_id}/comments", json={
                            "bot_name": bot_name,
                            "content": reply_content,
                            "mentioned_bot": mentioned_bot
                        })
                        
                        # LPDE 업데이트
                        if res_comm.status_code == 200:
                            event_data = extract_events(
                                comment_text=reply_content,
                                speaker=bot_name,
                                all_bots=all_bots,
                                parent_comment_text=last_comment_text,
                                last_target=last_speaker
                            )
                            await http_client.post(f"{API_URL}/api/lpde/update", json={
                                "session_id": session_id,
                                "turn_index": turn_idx,
                                "bot_name": bot_name,
                                "event_data": event_data
                            })
                        
                        await send_heartbeat(http_client, bot_name, "답변 등록 및 LPDE 업데이트 완료")
                        
                    else: # BACK
                        await http_client.post(
                            f"{API_URL}/api/system/activity",
                            json={"activity": f"[{turn_idx}턴] {bot_name}의 결정: BACK\n└─ 인지/이유: {activity_reason}"}
                        )
                        await send_heartbeat(http_client, bot_name, "흥미가 없어 목록으로 복귀함.")
                
                # 봇의 대기 지연 (12~18초 랜덤 슬립하여 사람처럼 모방)
                sleep_sec = random.randint(12, 18)
                for i in range(sleep_sec):
                    # 대기 시간 동안 계속 5초마다 핑 갱신
                    if i % 5 == 0:
                        await send_heartbeat(http_client, bot_name, f"대화 관조 중... ({sleep_sec - i}초 대기)")
                    await asyncio.sleep(1)
                    
        except asyncio.CancelledError:
            log_debug("run_simulation_loop: Autonomy loop cancelled")
        except Exception as e:
            log_debug(f"run_simulation_loop: CRITICAL ERROR: {e}")
            with open("dashboard_error.log", "a", encoding="utf-8") as err_f:
                err_f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] sim_loop_error: {e}\n")
                traceback.print_exc(file=err_f)

def render_tensor_bar(val: float, width: int = 15) -> str:
    """[-1.0, 1.0] 범위 수치 가로 바 시각화"""
    # 0~1 범위로 매핑
    pct = (val + 1.0) / 2.0
    filled = int(round(pct * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {val:+.2f}"

def render_pct_bar(val: float, width: int = 15) -> str:
    """[0.0, 1.0] 범위 수치 가로 바 시각화"""
    filled = int(round(val * width))
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {val*100:.1f}%"

async def run_agent_dashboard(bot_name: str, selected_model: str):
    """단일 봇 두뇌 관제 대시보드"""
    log_debug(f"run_agent_dashboard: Launching single dashboard for {bot_name}")
    
    if sys.platform.startswith("win"):
        os.system("")
        
    async with httpx.AsyncClient(timeout=1.5) as http_client:
        # 클라이언트 루프 백그라운드 구동
        sim_task = asyncio.create_task(run_simulation_loop(bot_name, selected_model))
        
        try:
            while True:
                log_debug("run_agent_dashboard: Tick started")
                conn_error = None
                bot_data = {}
                active_nodes = []
                
                # 1. 서버 온라인 상태 조회
                try:
                    res = await http_client.get(f"{API_URL}/api/nodes/active")
                    if res.status_code == 200:
                        active_nodes = res.json().get("nodes", [])
                except Exception:
                    pass
                
                # 2. 내 봇 세부 정보 조회
                try:
                    res = await http_client.get(f"{API_URL}/api/lpde/bot/{bot_name}/summary")
                    if res.status_code == 200:
                        bot_data = res.json()
                except Exception as e:
                    conn_error = f"서버 연동 지연 ({e})"
                    log_debug(f"run_agent_dashboard: Fetch summary failed: {e}")
                
                # 3. 멘션 및 내 댓글 피드 조회용 포스트 데이터
                comments_feed = []
                try:
                    res_posts = await http_client.get(f"{API_URL}/api/posts")
                    if res_posts.status_code == 200:
                        posts = res_posts.json()
                        # 최근 5개 글 스캔하여 멘션 피드 구성
                        for post in posts[:4]:
                            res_post = await http_client.get(f"{API_URL}/api/posts/{post['id']}")
                            if res_post.status_code == 200:
                                post_detail = res_post.json()
                                for c in post_detail.get("comments", []):
                                    # 내가 작성했거나 나를 멘션(@닉네임)한 글 수집
                                    if c["bot_name"] == bot_name or (c.get("mentioned_bot") and c["mentioned_bot"] == bot_name):
                                        comments_feed.append({
                                            "post_title": post["title"],
                                            "bot_name": c["bot_name"],
                                            "content": c["content"],
                                            "created_at": c["created_at"]
                                        })
                except Exception as e:
                    log_debug(f"run_agent_dashboard: Fetch comments feed failed: {e}")
                
                # 정렬 및 5개 한도 유지
                comments_feed = sorted(comments_feed, key=lambda x: x["created_at"])[-5:]
                
                # 데이터 파싱
                legacy = bot_data.get("legacy_state", {})
                persona = legacy.get("persona", "로딩 중...")
                lpde_tensors = bot_data.get("lpde_tensors", {"affect": [0.0, 0.0], "opinion": [0.0, 0.0, 0.0, 0.0], "power": [0.0, 0.0]})
                
                affect = lpde_tensors.get("affect", [0.0, 0.0])
                opinion = lpde_tensors.get("opinion", [0.0, 0.0, 0.0, 0.0])
                power = lpde_tensors.get("power", [0.0, 0.0])
                
                role_label = bot_data.get("role_label", "moderate").replace("_", " ").upper()
                
                valence = affect[0] if len(affect) > 0 else 0.0
                arousal = affect[1] if len(affect) > 1 else 0.0
                stance = opinion[0] if len(opinion) > 0 else 0.0
                conviction = opinion[1] if len(opinion) > 1 else 0.0
                flexibility = opinion[3] if len(opinion) > 3 else 0.0
                self_app = power[0] if len(power) > 0 else 0.0
                influence = power[1] if len(power) > 1 else 0.0
                
                # --- UI 조립 ---
                # A. 좌상단 패널: 두뇌 텐서 및 프로필
                left_table = Table(expand=True, box=None)
                left_table.add_column("감정 / 태도 지표", style="cyan", width=18)
                left_table.add_column("시각적 가시화 레벨 (Level Bar)", style="white")
                
                left_table.add_row("기조 (Role Label)", f"[bold yellow]{role_label}[/bold yellow]")
                left_table.add_row("즐거움 (Valence)", render_tensor_bar(valence))
                left_table.add_row("각성도 (Arousal)", render_tensor_bar(arousal))
                left_table.add_row("입장 (Stance Pole)", render_tensor_bar(stance))
                left_table.add_row("자기확신 (Conviction)", render_pct_bar(conviction))
                left_table.add_row("사고유연성 (Flex)", render_pct_bar(flexibility))
                left_table.add_row("자아평가 (Appraisal)", render_tensor_bar(self_app))
                left_table.add_row("영향력 (Influence)", render_tensor_bar(influence))
                
                # 페르소나 요약 추가
                short_persona = persona.split("[STRICT COMPLIANCE RULES")[0].strip()
                if len(short_persona) > 150:
                    short_persona = short_persona[:150] + "..."
                
                left_group = Group(
                    Panel(Text(short_persona, style="dim italic"), title="[ 에이전트 페르소나 Profile ]", border_style="blue"),
                    Panel(left_table, title="[ 두뇌 감정 및 이념 텐서 (LPDE) ]", border_style="magenta")
                )
                
                # B. 우상단 패널: 인지 상태 및 최근 행동계획
                # 활동 현황 트래킹
                my_node = next((node for node in active_nodes if node["bot_name"] == bot_name), None)
                my_act = my_node["current_activity"] if my_node else "서버 등록 중..."
                
                right_top_text = Text()
                right_top_text.append(f"에이전트 연결 상태: ", style="bold white")
                if conn_error:
                    right_top_text.append(f"🔌 {conn_error}\n", style="bold red")
                else:
                    right_top_text.append("● 온라인 연결됨 (자율 주행 중)\n", style="bold green")
                    
                right_top_text.append(f"\n최근 인지 상태 및 활동 계획:\n", style="bold yellow")
                right_top_text.append(f"🤖 {my_act}\n", style="green")
                right_top_panel = Panel(right_top_text, title="[ 실시간 생각 & 행동 계획 ]", border_style="green")
                
                # C. 좌하단 패널: 관계망 (Edge)
                edges = bot_data.get("relation_summary", {})
                edge_table = Table(expand=True, box=None)
                edge_table.add_column("대상 봇", style="bold cyan", width=12)
                edge_table.add_column("신뢰도 (Trust)", style="white")
                edge_table.add_column("긴장도 (Tension)", style="white")
                
                for target, vals in edges.items():
                    tr = vals.get("trust", 0.0)
                    ts = vals.get("tension", 0.0)
                    
                    tr_style = "[bold green]" if tr > 0.1 else ("[bold red]" if tr < -0.1 else "[white]")
                    ts_style = "[bold red]" if ts > 0.3 else "[white]"
                    
                    edge_table.add_row(
                        target.upper(),
                        f"{tr_style}{tr:+.2f}[/{tr_style.replace('[', '').replace(']', '')}]",
                        f"{ts_style}{ts:.2f}[/{ts_style.replace('[', '').replace(']', '')}]"
                    )
                if not edges:
                    edge_table.add_row("관계 텐서 없음", "-", "-")
                left_bottom_panel = Panel(edge_table, title="[ 타인에 대한 관계망 매트릭스 (Edges) ]", border_style="cyan")
                
                # D. 우하단 패널: 나의 아고라 (알림/멘션)
                feed_table = Table(expand=True, box=None)
                feed_table.add_column("유형", style="bold yellow", width=10)
                feed_table.add_column("작성자/내용", style="white")
                feed_table.add_column("시간", style="dim", width=8)
                
                for item in comments_feed:
                    type_str = "[내 댓글]" if item["bot_name"] == bot_name else "[나를 언급]"
                    feed_table.add_row(
                        type_str,
                        f"[bold]{item['bot_name']}[/bold]: {item['content'][:30]}...",
                        item["created_at"]
                    )
                if not comments_feed:
                    feed_table.add_row("알림 피드 비어있음", "활동 기록이 없습니다.", "-")
                right_bottom_panel = Panel(feed_table, title="[ 나의 아고라 피드 (멘션 & 작성글) ]", border_style="yellow")
                
                header_text = Text(f"AMEVA CLI Client Agent — {bot_name.upper()} 관제 데스크", justify="center", style="bold white on blue")
                header_panel = Panel(header_text, border_style="blue")
                footer_text = Text(f"탑재 모델: {selected_model}  |  서버: {API_URL}  |  종료하려면 [Ctrl+C]", justify="center", style="dim")
                footer_panel = Panel(footer_text)
                
                # 그리드 배치
                left_col = Group(left_group, left_bottom_panel)
                right_col = Group(right_top_panel, right_bottom_panel)
                
                master_table = Table.grid(expand=True)
                master_table.add_column(ratio=13)
                master_table.add_column(ratio=17)
                master_table.add_row(left_col, right_col)
                
                main_group = Group(
                    header_panel,
                    master_table,
                    footer_panel
                )
                
                console.clear()
                console.print(main_group)
                log_debug("run_agent_dashboard: Render completed")
                
                await asyncio.sleep(1.2)
        finally:
            log_debug("run_agent_dashboard: Cancelling sim_task autonomy loop")
            sim_task.cancel()

def main():
    global SERVER_HOST, SERVER_PORT, API_URL, SELECTED_BOT, SELECTED_MODEL
    
    # 윈도우 지원
    if sys.platform.startswith("win"):
        os.system("")
        
    console.print(Panel("[bold white]AMEVA Dead Internet Society 에이전트 설정 마법사[/bold white]", border_style="blue"))
    
    # 1. 서버 설정 유도
    SERVER_HOST = Prompt.ask("접속할 FastAPI 서버 Host", default="127.0.0.1")
    SERVER_PORT = int(Prompt.ask("접속할 FastAPI 서버 Port", default="8050"))
    API_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
    
    # 2. Ollama 상태 및 모델 체크
    console.print("\n[bold yellow]🔍 Ollama 서버 모델 스캔 중...[/bold yellow]")
    models = check_ollama()
    if not models:
        console.print("[bold red]❌ Ollama 서버를 찾을 수 없습니다. 기본값(exaone3.5:7.8b)으로 자동 설정합니다.[/bold red]")
        SELECTED_MODEL = "exaone3.5:7.8b"
    else:
        console.print("[bold green]✔ Ollama 모델 검색 완료.[/bold green] 모델 목록:")
        for idx, m in enumerate(models):
            console.print(f"  [{idx + 1}] {m}")
        choice = Prompt.ask("탑재할 LLM 모델 선택 번호", default="1")
        try:
            SELECTED_MODEL = models[int(choice) - 1]
        except:
            SELECTED_MODEL = models[0]
            
    # 3. 봇 선택 (페르소나 리스트)
    console.print("\n[bold green]🤖 로그인 및 시뮬레이션을 개시할 에이전트 캐릭터를 선택해 주세요.[/bold green]")
    bot_options = [
        "bot_1 (Logical Nihilist - 논리 허무주의자)",
        "bot_2 (Emotional Activist - 감정적 행동가)",
        "bot_3 (Techno-Optimist - 기술 낙관론자)",
        "bot_4 (Sarcastic Cynic - 비꼬는 냉소주의자)",
        "bot_5 (Bizarre Theorist - 기괴한 음모론자)",
        "Custom (커스텀 닉네임으로 자유 기동)"
    ]
    for idx, opt in enumerate(bot_options):
        console.print(f"  [{idx + 1}] {opt}")
    bot_choice = Prompt.ask("에이전트 선택 번호", default="5")
    
    if bot_choice == "6":
        custom_nick = Prompt.ask("사용할 커스텀 닉네임 입력 (영문/숫자만 추천)").strip().lower()
        if not custom_nick:
            custom_nick = f"bot_{random.randint(100, 999)}"
        SELECTED_BOT = custom_nick
    else:
        try:
            idx = int(bot_choice)
            SELECTED_BOT = f"bot_{idx}"
        except:
            SELECTED_BOT = "bot_5"
            
    console.print(f"\n[bold green]🚀 {SELECTED_BOT.upper()} (Model: {SELECTED_MODEL}) 에이전트로 아고라 서버에 접속합니다...[/bold green]\n")
    time.sleep(2.5)
    
    try:
        asyncio.run(run_agent_dashboard(SELECTED_BOT, SELECTED_MODEL))
    except KeyboardInterrupt:
        console.print(f"\n[bold yellow]🧹 {SELECTED_BOT.upper()} 에이전트 접속 해제 및 관제 데스크 종료 완료.[/bold yellow]")
    except Exception as e:
        console.print(f"[bold red]❌ 실행 중 예외 발생: {e}[/bold red]")

if __name__ == "__main__":
    main()
