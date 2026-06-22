import os
import sys
import time
import subprocess
import httpx
import psutil
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.prompt import Prompt

console = Console()

API_URL = "http://127.0.0.1:8050"
OLLAMA_URL = "http://127.0.0.1:11434"

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

def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    layout["main"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=2)
    )
    layout["right"].split_column(
        Layout(name="thought", ratio=1),
        Layout(name="comments", ratio=2)
    )
    return layout

async def run_dashboard(selected_model: str):
    layout = make_layout()
    
    # 헬더 렌더링
    header_text = Text("AMEVA CLI Arena - Dead Internet Simulation", justify="center", style="bold white on blue")
    layout["header"].update(Panel(header_text, border_style="blue"))
    
    # 푸터 렌더링
    footer_text = Text(f"모델: {selected_model}  |  서버 주소: {API_URL}  |  종료하려면 [Ctrl+C]", justify="center", style="dim")
    layout["footer"].update(Panel(footer_text))
    
    with Live(layout, refresh_per_second=1, screen=True) as live:
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            # 시뮬레이터 트리거
            try:
                await http_client.post(f"{API_URL}/api/control/new")
            except Exception as e:
                logger_msg = f"시뮬레이터 기동 요청 오류: {e}"
                
            while True:
                # 1. 시스템 정보 읽기
                status_data = {}
                try:
                    res = await http_client.get(f"{API_URL}/api/system/status")
                    if res.status_code == 200:
                        status_data = res.json()
                except Exception:
                    pass
                
                # 2. 에이전트 정보 및 감정 텐서 읽기
                bot_states = []
                session_status = "UNKNOWN"
                try:
                    res = await http_client.get(f"{API_URL}/api/bots/state")
                    if res.status_code == 200:
                        res_data = res.json()
                        bot_states = res_data.get("states", [])
                        session_status = res_data.get("session_status", "UNKNOWN")
                except Exception:
                    pass
                
                # 3. 최신 게시글 목록 읽기
                posts = []
                try:
                    res = await http_client.get(f"{API_URL}/api/posts")
                    if res.status_code == 200:
                        posts = res.json()
                except Exception:
                    pass
                
                # 4. 활성화된 최신 글의 댓글 읽기
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
                
                # --- UI 업데이트 ---
                # A. 좌측 패널: 에이전트 감정 벡터 & 지표
                left_table = Table(title="[에이전트 LPDE 감정 벡터]", expand=True, box=None)
                left_table.add_column("봇 이름", style="bold magenta")
                left_table.add_column("유효 분노", style="bold red")
                left_table.add_column("분노 대상", style="dim text")
                
                for bot in bot_states:
                    eff = bot.get("effective_anger", 0.0)
                    targets = bot.get("anger_targets", {})
                    target_str = ", ".join([f"{k}:{v}" for k, v in targets.items()])
                    left_table.add_row(bot["bot_name"].upper(), f"{eff:.1f}", target_str or "평온")
                    
                layout["left"].update(Panel(left_table, title="[ 에이전트 감정 지표 ]", border_style="magenta"))
                
                # B. 우상단 패널: 실시간 생각/활동 로그
                current_act = status_data.get("current_activity", "대기 중...")
                state_val = status_data.get("state", "IDLE")
                
                thought_text = Text()
                thought_text.append(f"시뮬레이터 상태: {state_val}\n", style="bold yellow")
                thought_text.append(f"현재 토론 게시글: {current_post_title}\n\n", style="bold white")
                thought_text.append(f"활동 기록:\n", style="bold green")
                thought_text.append(f"🤖 {current_act}\n", style="green")
                layout["thought"].update(Panel(thought_text, title="[ 실시간 생각 & 행동 계획 ]", border_style="green"))
                
                # C. 우하단 패널: 최신 댓글 피드
                comment_table = Table(expand=True, box=None)
                comment_table.add_column("작성자", style="bold cyan", width=12)
                comment_table.add_column("내용", style="white")
                comment_table.add_column("시간", style="dim grey", width=10)
                
                # 최신 댓글 5개 출력
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
                        
                    content = c["content"]
                    comment_table.add_row(bot_styled, content, c["created_at"])
                    
                layout["comments"].update(Panel(comment_table, title="[ 실시간 게시판 댓글 피드 ]", border_style="cyan"))
                
                await asyncio.sleep(1)

def main():
    console.print(Panel("[bold white]AMEVA Dead Internet Arena CLI 테스트 실행기[/bold white]\nOllama 서버 검진 및 자동 설정을 시작합니다.", border_style="blue"))
    
    # 1. Ollama 구동 체크
    models = check_ollama()
    if not models:
        console.print("[bold red]❌ Ollama 서버가 켜져 있지 않습니다.[/bold red]")
        console.print("Ollama가 정상적으로 백그라운드에서 기동 중인지 확인해 주세요. (기본 포트: 11434)")
        console.print("Ollama가 없으시다면 https://ollama.com 에서 설치 후 모델을 구동하세요.")
        sys.exit(1)
        
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
    server_running = is_port_in_use(8050)
    server_proc = None
    if not server_running:
        console.print("[bold yellow]⚡ 포트 8050에서 게시판 서버(FastAPI)가 비활성 상태입니다. 백그라운드로 자동 구동합니다...[/bold yellow]")
        try:
            server_proc = subprocess.Popen([sys.executable, "run.py"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # 서버가 뜰 때까지 잠시 대기
            for _ in range(15):
                time.sleep(1)
                if is_port_in_use(8050):
                    server_running = True
                    break
        except Exception as e:
            console.print(f"[bold red]❌ 웹 서버를 기동하는 데 실패했습니다: {e}[/bold red]")
            sys.exit(1)
            
    if server_running:
        console.print("[bold green]✔ 게시판 웹 서버 연결 완료.[/bold green]")
    else:
        console.print("[bold red]❌ 게시판 서버가 켜지지 않았습니다. python run.py 명령어로 수동 구동 후 재실행해 주세요.[/bold red]")
        if server_proc:
            server_proc.kill()
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

if __name__ == "__main__":
    main()
