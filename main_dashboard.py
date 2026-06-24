import os
import sys
import time
import asyncio
import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import rich.box as rbox

# Windows 인코딩 예외 방지 및 가상 터미널 지원 강제 활성화
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        os.system("")
    except Exception:
        pass

load_dotenv()

# Rich 테두리 스타일 결정 (윈도우 기본 CMD/PowerShell 인코딩 호환을 위해 ASCII 폴백 제공)
BOX_STYLE = rbox.ASCII if os.getenv("CLI_ASCII", "false").lower() == "true" or sys.platform.startswith("win") else rbox.ROUNDED

console = Console()

# 환경변수 기본값 (DIT 서버 모니터링 포트)
SERVER_HOST = os.getenv("SERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("DIT_PORT", os.getenv("SERVER_PORT", "8080")))
API_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

def log_debug(msg: str):
    try:
        with open("main_debug.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def calculate_effective_anger(anger_dict: dict) -> float:
    import math
    if not anger_dict or not isinstance(anger_dict, dict):
        return 0.0
    sum_sq = 0.0
    for val in anger_dict.values():
        try:
            sum_sq += float(val) ** 2
        except:
            continue
    return math.sqrt(sum_sq)

async def run_global_dashboard():
    log_debug("run_global_dashboard: Starting Global Theater View")
    
    # 윈도우 가상 터미널 지원 강제 활성화
    if sys.platform.startswith("win"):
        os.system("")
        
    async with httpx.AsyncClient(timeout=1.5) as http_client:
        try:
            while True:
                log_debug("run_global_dashboard: Tick start")
                conn_error = None
                status_data = {}
                
                # 1. 서버 상태 정보 로드
                try:
                    res = await http_client.get(f"{API_URL}/api/system/status")
                    if res.status_code == 200:
                        status_data = res.json()
                except Exception as e:
                    conn_error = f"서버 연결 오류 ({e})"
                    log_debug(f"run_global_dashboard: Fetch status failed: {e}")
                
                # 2. 봇 상태 리스트 로드
                bot_states = []
                try:
                    res = await http_client.get(f"{API_URL}/api/bots/state")
                    if res.status_code == 200:
                        res_data = res.json()
                        bot_states = res_data.get("states", [])
                except Exception as e:
                    log_debug(f"run_global_dashboard: Fetch bot states failed: {e}")
                
                # 3. 실시간 온라인 노드(봇) 조회
                active_nodes = []
                try:
                    res = await http_client.get(f"{API_URL}/api/nodes/active")
                    if res.status_code == 200:
                        active_data = res.json()
                        active_nodes = active_data.get("nodes", [])
                except Exception as e:
                    log_debug(f"run_global_dashboard: Fetch active nodes failed: {e}")
                
                # 4. 최근 게시글 및 댓글 피드 로드
                posts = []
                comments = []
                current_post_title = "대화 없음"
                try:
                    res = await http_client.get(f"{API_URL}/api/posts")
                    if res.status_code == 200:
                        posts = res.json()
                        if posts:
                            latest_post_id = posts[0]["id"]
                            current_post_title = posts[0]["title"]
                            res_post = await http_client.get(f"{API_URL}/api/posts/{latest_post_id}")
                            if res_post.status_code == 200:
                                comments = res_post.json().get("comments", [])
                except Exception as e:
                    log_debug(f"run_global_dashboard: Fetch posts/comments failed: {e}")
                
                # --- UI 조립 ---
                # A. 좌측 패널: 에이전트 상세 상태 요약 및 접속 여부
                left_table = Table(expand=True, box=None)
                left_table.add_column("에이전트", style="bold magenta", width=14)
                left_table.add_column("상태", style="bold green", width=8)
                left_table.add_column("기조 (Role)", style="cyan", width=16)
                left_table.add_column("입장 (Stance)", style="white", justify="right", width=10)
                left_table.add_column("확신 (Conv)", style="yellow", justify="right", width=8)
                left_table.add_column("분노 (Anger)", style="bold red", justify="right", width=8)
                
                # 온라인인 봇 이름 목록 추출
                online_names = {node["bot_name"].lower() for node in active_nodes}
                nickname_map = {
                    "bot_1": "Logical Nihilist",
                    "bot_2": "Emotional Activist",
                    "bot_3": "Techno-Optimist",
                    "bot_4": "Sarcastic Cynic",
                    "bot_5": "Bizarre Theorist"
                }
                
                for bot in bot_states:
                    bot_name_raw = bot["bot_name"]
                    is_online = bot_name_raw.lower() in online_names
                    status_str = "[bold green]● 온라인[/bold green]" if is_online else "[dim red]○ 오프라인[/dim red]"
                    
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
                    
                    nick = nickname_map.get(bot_name_raw, "Guest Node")
                    bot_display = f"{bot_name_raw.upper()}\n[dim gray]({nick})[/dim gray]"
                    
                    left_table.add_row(
                        bot_display,
                        status_str,
                        role.upper(),
                        stance_str,
                        conv_str,
                        f"{eff:.1f}"
                    )
                    
                left_panel = Panel(left_table, title="[ 에이전트 통합 접속 & 상태 관제 ]", border_style="magenta", box=BOX_STYLE)
                
                # B. 우상단 패널: 실시간 시뮬레이터 현황
                current_act = status_data.get("current_activity", "대기 중...")
                state_val = status_data.get("state", "IDLE")
                
                # 하드웨어 정보
                hw_mode = "CPU"
                if active_nodes:
                    hw_mode = active_nodes[0].get("hardware_mode", "CPU")
                    
                thought_text = Text()
                thought_text.append(f"시뮬레이터 상태: {state_val} (서버 활성 노드: {len(active_nodes)} Nodes)\n", style="bold yellow")
                if conn_error:
                    thought_text.append(f"🔌 연결 상태: {conn_error}\n", style="bold red")
                else:
                    thought_text.append(f"현재 토론 아고라: {current_post_title}\n\n", style="bold white")
                    
                thought_text.append(f"활동 및 인지 기록 로그:\n", style="bold green")
                thought_text.append(f"{current_act}\n", style="green")
                thought_panel = Panel(thought_text, title="[ 실시간 극장 중계 & 서버 로그 ]", border_style="green", box=BOX_STYLE)
                
                # C. 우하단 패널: 통합 댓글 피드
                comment_table = Table(expand=True, box=None)
                comment_table.add_column("작성자", style="bold cyan", width=12)
                comment_table.add_column("내용", style="white")
                comment_table.add_column("시간", style="dim", width=10)
                
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
                    
                comment_panel = Panel(comment_table, title="[ 실시간 전체 게시판 댓글 피드 ]", border_style="cyan", box=BOX_STYLE)
                
                header_text = Text("AMEVA CLI Theater - Global Observer Dashboard", justify="center", style="bold white on purple")
                header_panel = Panel(header_text, border_style="purple", box=BOX_STYLE)
                footer_text = Text(f"서버 주소: {API_URL}  |  종료하려면 [Ctrl+C]", justify="center", style="dim")
                footer_panel = Panel(footer_text, box=BOX_STYLE)
                
                from rich.console import Group
                master_table = Table.grid(expand=True)
                master_table.add_column(ratio=13)
                master_table.add_column(ratio=17)
                master_table.add_row(left_panel, Group(thought_panel, comment_panel))
                
                main_group = Group(
                    header_panel,
                    master_table,
                    footer_panel
                )
                
                console.clear()
                console.print(main_group)
                log_debug("run_global_dashboard: Render completed")
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            console.print("\n[bold yellow]👋 글로벌 모니터링을 종료합니다.[/bold yellow]")
        except Exception as e:
            log_debug(f"run_global_dashboard: Global Exception: {e}")
            console.print(f"[bold red]❌ 대시보드 실행 중 오류 발생: {e}[/bold red]")

def main():
    try:
        asyncio.run(run_global_dashboard())
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
