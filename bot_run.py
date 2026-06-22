import os
import sys
import time
import asyncio
import subprocess
import httpx
import psutil
import json
import random

# Windows 인코딩 이슈 방지 (CP949 -> UTF-8 강제 설정)
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.prompt import Prompt

# AMEVA 로컬 모듈 임포트
from app.services.llm.client import LLMClient
from app.core.prompt_adapter import prompt_adapter
from app.core.event_extractor import extract_events
from app.core.stance_roles import assign_initial_role_triplet

console = Console()

def load_env():
    """.env 파일을 수동으로 파싱하여 환경 변수에 주입합니다."""
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip("'\"")
                    os.environ[key.strip()] = val
    # APP_PORT -> SERVER_PORT, APP_HOST -> SERVER_HOST 매핑
    if "APP_PORT" in os.environ and "SERVER_PORT" not in os.environ:
        os.environ["SERVER_PORT"] = os.environ["APP_PORT"]
    if "APP_HOST" in os.environ and "SERVER_HOST" not in os.environ:
        os.environ["SERVER_HOST"] = os.environ["APP_HOST"]

# 환경변수 로드
load_env()

SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8050"))
API_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
OLLAMA_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434")

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

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

def update_env_model(model_name: str):
    """.env 파일 내 LLM_MODEL_NAME 변수 갱신"""
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"LLM_MODEL_NAME={model_name}\n")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated = False
    for i, line in enumerate(lines):
        if line.strip().startswith("LLM_MODEL_NAME="):
            lines[i] = f"LLM_MODEL_NAME={model_name}\n"
            updated = True
            break

    if not updated:
        lines.append(f"\nLLM_MODEL_NAME={model_name}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

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

async def run_simulation_loop(selected_model: str):
    """클라이언트 사이드 시뮬레이션 오케스트레이터 루프 (5인 봇)"""
    llm_client = LLMClient(model_name=selected_model)
    
    async with httpx.AsyncClient(timeout=2.0) as http_client:
        session_id = None
        try:
            # 1. 새 세션 생성 API 호출
            await http_client.post(f"{API_URL}/api/system/activity", json={"activity": "시뮬레이션 초기화 중...", "state": "RUNNING"})
            
            res = await http_client.post(f"{API_URL}/api/sessions", json={"status": "ACTIVE", "reason": "Organic CLI browsing simulation started"})
            res.raise_for_status()
            session_data = res.json()
            session_id = session_data["id"]
            
            # 2. 페르소나 초기화 및 스탠스 할당 (5봇용)
            role_triplet = assign_initial_role_triplet()
            
            # 3. 에이전트 초기 상태 할당 API 호출
            res = await http_client.post(f"{API_URL}/api/lpde/initialize", json={"session_id": session_id, "role_triplet": role_triplet})
            res.raise_for_status()
            
            # 4. 시드 게시글 생성 (글이 없는 경우)
            res = await http_client.get(f"{API_URL}/api/posts")
            res.raise_for_status()
            posts = res.json()
            
            if not posts:
                await http_client.post(f"{API_URL}/api/system/activity", json={"activity": "초기 화두 게시글 생성 중..."})
                post_data = await create_post_with_main_llm(llm_client)
                res = await http_client.post(f"{API_URL}/api/posts", json={
                    "title": post_data["title"],
                    "content": post_data["content"],
                    "bot_name": "SYSTEM"
                })
                res.raise_for_status()
                
            # 5. 브라우징 루프 시작 (최대 100턴)
            bots = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]
            
            for turn_idx in range(100):
                current_bot = bots[turn_idx % len(bots)]
                
                await http_client.post(
                    f"{API_URL}/api/system/activity",
                    json={"activity": f"[{turn_idx+1}턴] {current_bot}이 게시글 정독 위치로 이동 중..."}
                )
                
                # A. 게시판 글 목록 로드
                res = await http_client.get(f"{API_URL}/api/posts")
                res.raise_for_status()
                posts = res.json()
                
                if not posts:
                    await asyncio.sleep(3)
                    continue
                
                # B. 조회할 게시글 선택 (최신 글 위주로 확률적 선택)
                selected_post = random.choice(posts)
                post_id = selected_post["id"]
                
                await http_client.post(
                    f"{API_URL}/api/system/activity",
                    json={"activity": f"[{turn_idx+1}턴] {current_bot}이 '{selected_post['title']}' 글을 읽는 중..."}
                )
                
                # C. 글 상세 내용 및 댓글 로드
                res = await http_client.get(f"{API_URL}/api/posts/{post_id}")
                res.raise_for_status()
                post_detail = res.json()
                
                # D. 행동 결정 (Reply, Write Post, Back)
                res = await http_client.get(f"{API_URL}/api/lpde/bot/{current_bot}/summary?session_id={session_id}")
                res.raise_for_status()
                bot_summary = res.json()
                
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
                except Exception:
                    pass
                
                # E. 행동 실행
                if action_choice == "REPLY":
                    await http_client.post(
                        f"{API_URL}/api/system/activity",
                        json={"activity": f"[{turn_idx+1}턴] {current_bot}이 댓글 생성 중..."}
                    )
                    
                    last_comment_text = comments_list[-1]["content"] if comments_list else post_detail["content"]
                    last_speaker = comments_list[-1]["bot_name"] if comments_list else "SYSTEM"
                    
                    claim_snippet = last_comment_text[:100]
                    
                    prompt = prompt_adapter.build_prompt(
                        current_bot=current_bot,
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
                    
                    other_bots = [b for b in bots if b != current_bot]
                    mentioned_bot = None
                    for ob in other_bots:
                        if f"@{ob}" in reply_content:
                            mentioned_bot = ob
                            break
                            
                    res = await http_client.post(f"{API_URL}/api/posts/{post_id}/comments", json={
                        "bot_name": current_bot,
                        "content": reply_content,
                        "mentioned_bot": mentioned_bot
                    })
                    res.raise_for_status()
                    
                    event_data = extract_events(
                        comment_text=reply_content,
                        speaker=current_bot,
                        all_bots=bots,
                        parent_comment_text=last_comment_text,
                        last_target=last_speaker
                    )
                    
                    res = await http_client.post(f"{API_URL}/api/lpde/update", json={
                        "session_id": session_id,
                        "turn_index": turn_idx,
                        "bot_name": current_bot,
                        "event_data": event_data
                    })
                    res.raise_for_status()
                    
                elif action_choice == "WRITE_POST":
                    await http_client.post(
                        f"{API_URL}/api/system/activity",
                        json={"activity": f"[{turn_idx+1}턴] {current_bot}이 새 글 주제 생성 중..."}
                    )
                    post_data = await create_post_with_main_llm(llm_client)
                    
                    res = await http_client.post(f"{API_URL}/api/posts", json={
                        "title": post_data["title"],
                        "content": post_data["content"],
                        "bot_name": current_bot
                    })
                    res.raise_for_status()
                    
                else: # BACK
                    await http_client.post(
                        f"{API_URL}/api/system/activity",
                        json={"activity": f"[{turn_idx+1}턴] {current_bot}이 관심이 없어 목록으로 복귀함."}
                    )
                    
                # 턴 사이의 슬립 대기 (초 단위)
                await asyncio.sleep(5)
                
            # 세션 종료 처리
            await http_client.post(f"{API_URL}/api/sessions/{session_id}/update", json={
                "status": "CLOSED",
                "reason": "MAX_TURNS_REACHED"
            })
            await http_client.post(f"{API_URL}/api/system/activity", json={"activity": "시뮬레이션 완료", "state": "IDLE"})
            
        except asyncio.CancelledError:
            if session_id:
                try:
                    await http_client.post(f"{API_URL}/api/sessions/{session_id}/update", json={
                        "status": "CLOSED",
                        "reason": "CLIENT_TERMINATED"
                    })
                except Exception:
                    pass
            try:
                await http_client.post(f"{API_URL}/api/system/activity", json={"activity": "시뮬레이션 중단됨 (대기 상태)", "state": "IDLE"})
            except Exception:
                pass
        except Exception as e:
            try:
                await http_client.post(f"{API_URL}/api/system/activity", json={"activity": f"에러 발생: {e}", "state": "ERROR"})
            except Exception:
                pass

async def run_dashboard(selected_model: str):
    from rich.console import Group
    
    # 처음부터 전체 레이아웃 구조를 가진 플레이스홀더를 넘겨주어 높이 변화로 인한 파워쉘 렌더링 락 방지
    init_left = Panel(Text("에이전트 정보 로딩 중...", style="dim"), title="[ 에이전트 상세 상태 & 감정 ]", border_style="magenta")
    init_thought = Panel(Text("시뮬레이터 연산 초기화 중...", style="dim"), title="[ 실시간 생각 & 행동 계획 ]", border_style="green")
    init_comments = Panel(Text("댓글 피드 수신 대기 중...", style="dim"), title="[ 실시간 게시판 댓글 피드 ]", border_style="cyan")
    
    init_table = Table.grid(expand=True)
    init_table.add_column(ratio=11)
    init_table.add_column(ratio=19)
    init_table.add_row(init_left, Group(init_thought, init_comments))
    
    init_layout = Group(
        Panel(Text("AMEVA CLI Arena - Dead Internet Simulation", justify="center", style="bold white on blue"), border_style="blue"),
        init_table,
        Panel(Text("서버와 통신 채널을 동기화하고 있습니다...", justify="center", style="dim"))
    )
    
    # Live 객체를 동일 높이의 플레이스홀더 레이아웃으로 시작
    with Live(init_layout, refresh_per_second=1, screen=False) as live:
        # HTTP 클라이언트 타임아웃을 1.2초로 대폭 단축하여 지연 해결
        async with httpx.AsyncClient(timeout=1.2) as http_client:
            
            # 클라이언트 측 시뮬레이션 태스크 기동
            sim_task = asyncio.create_task(run_simulation_loop(selected_model))
            
            try:
                while True:
                    conn_error = None
                    status_data = {}
                    try:
                        res = await http_client.get(f"{API_URL}/api/system/status")
                        if res.status_code == 200:
                            status_data = res.json()
                    except Exception as e:
                        conn_error = f"연결 지연/대기 ({e})"
                    
                    bot_states = []
                    try:
                        res = await http_client.get(f"{API_URL}/api/bots/state")
                        if res.status_code == 200:
                            res_data = res.json()
                            bot_states = res_data.get("states", [])
                    except Exception:
                        pass
                    
                    posts = []
                    try:
                        res = await http_client.get(f"{API_URL}/api/posts")
                        if res.status_code == 200:
                            posts = res.json()
                    except Exception:
                        pass
                    
                    comments = []
                    current_post_title = "대화 없음"
                    if posts:
                        latest_post_id = posts[0]["id"]
                        current_post_title = posts[0]["title"]
                        try:
                            res = await http_client.get(f"{API_URL}/api/posts/{latest_post_id}")
                            if res.status_code == 200:
                                post_detail = res.json()
                                comments = post_detail.get("comments", [])
                        except Exception:
                            pass
                    
                    # --- UI 조립 ---
                    # A. 좌측 패널: 에이전트 상세 상태 (5봇용)
                    left_table = Table(expand=True, box=None)
                    left_table.add_column("에이전트", style="bold magenta", width=8)
                    left_table.add_column("기조 (Role)", style="cyan", width=16)
                    left_table.add_column("입장 (Stance)", style="white", justify="right", width=12)
                    left_table.add_column("확신 (Conv)", style="yellow", justify="right", width=10)
                    left_table.add_column("분노 (Anger)", style="bold red", justify="right", width=10)
                    
                    for bot in bot_states:
                        eff = bot.get("effective_anger", 0.0)
                        role = bot.get("role_label", "moderate").replace("_", " ")
                        opinion = bot.get("opinion", [0.0, 0.0, 0.0, 0.0])
                        stance_pole = opinion[0] if len(opinion) > 0 else 0.0
                        conviction = opinion[1] if len(opinion) > 1 else 0.0
                        
                        if stance_pole > 0.05:
                            stance_str = f"[bold green]+{stance_pole:.2f}[/bold green]"
                        elif stance_pole < -0.05:
                            stance_str = f"[bold red]{stance_pole:.2f}[/bold red]"
                        else:
                            stance_str = "0.00"
                            
                        conv_str = f"{conviction*100:.1f}%"
                        
                        left_table.add_row(
                            bot["bot_name"].upper(),
                            role.upper(),
                            stance_str,
                            conv_str,
                            f"{eff:.1f}"
                        )
                        
                    left_panel = Panel(left_table, title="[ 에이전트 상세 상태 & 감정 ]", border_style="magenta")
                    
                    # B. 우상단 패널: 생각 및 활동 진단
                    current_act = status_data.get("current_activity", "대기 중...")
                    state_val = status_data.get("state", "IDLE")
                    
                    hw_mode = "CPU"
                    try:
                        res_nodes = await http_client.get(f"{API_URL}/api/nodes/active")
                        if res_nodes.status_code == 200:
                            nodes_data = res_nodes.json()
                            if nodes_data.get("nodes"):
                                hw_mode = nodes_data["nodes"][0].get("hardware_mode", "CPU")
                    except Exception:
                        pass
                    
                    thought_text = Text()
                    thought_text.append(f"시뮬레이터 상태: {state_val} (연산 모드: {hw_mode})\n", style="bold yellow")
                    
                    if conn_error:
                        thought_text.append(f"🔌 연결 상태: {conn_error}\n", style="bold red")
                    else:
                        thought_text.append(f"현재 토론 게시글: {current_post_title}\n\n", style="bold white")
                        
                    thought_text.append(f"활동 기록:\n", style="bold green")
                    thought_text.append(f"🤖 {current_act}\n", style="green")
                    thought_panel = Panel(thought_text, title="[ 실시간 생각 & 행동 계획 ]", border_style="green")
                    
                    # C. 우하단 패널: 실시간 댓글 피드
                    comment_table = Table(expand=True, box=None)
                    comment_table.add_column("작성자", style="bold cyan", width=12)
                    comment_table.add_column("내용", style="white")
                    comment_table.add_column("시간", style="dim gray", width=10)
                    
                    for c in comments[-6:]:
                        bot_styled = c["bot_name"]
                        if c["bot_name"] == "USER":
                            bot_styled = f"[bold green]{c['bot_name']}[/bold green]"
                        elif c["bot_name"] == "bot_1":
                            bot_styled = f"[bold purple]{c['bot_name']}[/bold purple]"
                        elif c["bot_name"] == "bot_2":
                            bot_styled = f"[bold pink]{c['bot_name']}[/bold pink]"
                        elif c["bot_name"] == "bot_3":
                            bot_styled = f"[bold yellow]{c['bot_name']}[/bold yellow]"
                        elif c["bot_name"] == "bot_4":
                            bot_styled = f"[bold blue]{c['bot_name']}[/bold blue]"
                        elif c["bot_name"] == "bot_5":
                            bot_styled = f"[bold orange3]{c['bot_name']}[/bold orange3]"
                            
                        content = c["content"]
                        comment_table.add_row(bot_styled, content, c["created_at"])
                        
                    comment_panel = Panel(comment_table, title="[ 실시간 게시판 댓글 피드 ]", border_style="cyan")
                    
                    header_text = Text("AMEVA CLI Arena - Dead Internet Simulation", justify="center", style="bold white on blue")
                    header_panel = Panel(header_text, border_style="blue")
                    footer_text = Text(f"모델: {selected_model}  |  서버 주소: {API_URL}  |  종료하려면 [Ctrl+C]", justify="center", style="dim")
                    footer_panel = Panel(footer_text)
                    
                    # 마스터 테이블 레이아웃 구성
                    master_table = Table.grid(expand=True)
                    master_table.add_column(ratio=11)
                    master_table.add_column(ratio=19)
                    master_table.add_row(left_panel, Group(thought_panel, comment_panel))
                    
                    main_group = Group(
                        header_panel,
                        master_table,
                        footer_panel
                    )
                    
                    live.update(main_group)
                    
                    await asyncio.sleep(1)
            finally:
                sim_task.cancel()

def main():
    console.print(Panel("[bold white]AMEVA Dead Internet Arena CLI 테스트 실행기[/bold white]\nOllama 서버 검진 및 자동 설정을 시작합니다.", border_style="blue"))
    
    # 1. Ollama 구동 체크
    models = check_ollama()
    if not models:
        console.print("[bold red]❌ Ollama 서버가 켜져 있지 않습니다.[/bold red]")
        console.print(f"Ollama가 정상적으로 백그라운드에서 기동 중인지 확인해 주세요. (타겟 주소: {OLLAMA_URL})")
        console.print("Ollama가 없으시다면 https://ollama.com 에서 설치 후 모델을 구동하세요.")
        sys.exit(1)
        
    selected_model = None
    if len(sys.argv) > 1 and sys.argv[1] in ("--model", "-m"):
        if len(sys.argv) > 2:
            arg_model = sys.argv[2]
            if arg_model in models:
                selected_model = arg_model
            else:
                try:
                    idx = int(arg_model)
                    if 1 <= idx <= len(models):
                        selected_model = models[idx - 1]
                except ValueError:
                    pass
            
            if not selected_model:
                console.print(f"[bold yellow]⚠ 지정된 모델/번호 '{arg_model}'이 유효하지 않아 첫 번째 모델로 대체합니다.[/bold yellow]")
                selected_model = models[0]
    
    if not selected_model:
        console.print(f"[bold green]✔ Ollama 기동 확인 완료.[/bold green] 사용 가능한 모델 목록:")
        for idx, model in enumerate(models):
            console.print(f" [{idx + 1}] {model}")
            
        choice = Prompt.ask("사용할 모델 번호를 입력하세요 (예: 1)", default="1")
        try:
            selected_model = models[int(choice) - 1]
        except Exception:
            selected_model = models[0]
        
    console.print(f"[bold green]✔ '{selected_model}' 모델을 탑재하기 위해 설정을 저장했습니다.[/bold green]")
    update_env_model(selected_model)
    
    # 2. FastAPI 서버 체크 및 자동 구동
    server_running = is_port_in_use(SERVER_PORT)
    server_proc = None
    log_file = None
    if not server_running:
        console.print(f"[bold yellow]⚡ 포트 {SERVER_PORT}에서 게시판 서버(FastAPI)가 비활성 상태입니다. 백그라운드로 자동 구동합니다...[/bold yellow]")
        try:
            env = os.environ.copy()
            env["APP_RELOAD"] = "false"
            log_file = open("server.log", "w", encoding="utf-8")
            server_proc = subprocess.Popen(
                [sys.executable, "run.py"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env
            )
            # 서버가 뜰 때까지 잠시 대기
            for _ in range(15):
                time.sleep(1)
                if is_port_in_use(SERVER_PORT):
                    server_running = True
                    break
        except Exception as e:
            console.print(f"[bold red]❌ 웹 서버를 기동하는 데 실패했습니다: {e}[/bold red]")
            if log_file:
                log_file.close()
            sys.exit(1)
            
    if server_running:
        console.print("[bold green]✔ 게시판 웹 서버 연결 완료.[/bold green]")
    else:
        console.print("[bold red]❌ 게시판 서버가 켜지지 않았습니다. python run.py 명령어로 수동 구동 후 재실행해 주세요.[/bold red]")
        if server_proc:
            server_proc.kill()
        if log_file:
            log_file.close()
        sys.exit(1)
        
    # 3. rich 대시보드 구동
    try:
        asyncio.run(run_dashboard(selected_model))
    except KeyboardInterrupt:
        console.print("\n[bold yellow]👋 테스트 대시보드를 종료합니다.[/bold yellow]")
    finally:
        if server_proc:
            console.print("[bold yellow]🧹 백그라운드에서 실행된 웹 서버 프로세스를 정리합니다...[/bold yellow]")
            server_proc.kill()
            try:
                server_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        if log_file:
            log_file.close()

if __name__ == "__main__":
    main()
