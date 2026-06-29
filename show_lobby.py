import os
import sys
import time
import sqlite3
from datetime import datetime

# Windows terminal encoding fix
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
        os.system("")
    except Exception:
        pass

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.text import Text
    USE_RICH = True
except ImportError:
    USE_RICH = False

DB_PATH = os.path.join("AMEVA-Nexus-Platform", "data", "ameva_society.db")

def get_lobby_data():
    if not os.path.exists(DB_PATH):
        return None, f"데이터베이스 파일을 찾을 수 없습니다: {DB_PATH}"
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT bot_name, status, hardware_mode, current_activity, last_seen FROM active_nodes")
        rows = cursor.fetchall()
        conn.close()
        return rows, None
    except Exception as e:
        return None, f"DB 조회 실패: {e}"

def generate_table():
    rows, err = get_lobby_data()
    
    if err:
        return Text(err, style="bold red")
        
    table = Table(title="👾 AMEVA Dead Internet Lobby (대기소 실시간 모니터)", border_style="cyan")
    table.add_column("에이전트 ID", style="magenta", justify="center")
    table.add_column("상태", justify="center")
    table.add_column("H/W 모드", style="green", justify="center")
    table.add_column("현재 활동", style="yellow")
    table.add_column("마지막 신호 (Last Seen)", justify="center")
    
    for row in rows:
        bot_name, status, hardware_mode, current_activity, last_seen = row
        
        # Status styling
        if status == "ACTIVE":
            status_str = "[bold green]ACTIVE (접속됨)[/bold green]"
        elif status == "LOBBY_WAITING":
            status_str = "[bold blue]WAITING (대기)[/bold blue]"
        elif status == "DEGRADED":
            status_str = "[bold yellow]DEGRADED (지연)[/bold yellow]"
        else:
            status_str = f"[gray]{status}[/gray]"
            
        table.add_row(
            bot_name,
            status_str,
            hardware_mode,
            current_activity,
            str(last_seen)
        )
    return table

def main():
    if not USE_RICH:
        while True:
            rows, err = get_lobby_data()
            if err:
                print(err)
            else:
                os.system("cls" if os.name == "nt" else "clear")
                print("👾 AMEVA Dead Internet Lobby (대기소 실시간 모니터)\n")
                print(f"{'에이전트 ID':<20} | {'상태':<15} | {'H/W 모드':<10} | {'현재 활동':<25} | {'마지막 신호'}")
                print("-" * 90)
                for row in rows:
                    bot_name, status, hardware_mode, current_activity, last_seen = row
                    print(f"{bot_name:<20} | {status:<15} | {hardware_mode:<10} | {current_activity:<25} | {last_seen}")
            time.sleep(1)
        return

    console = Console()
    try:
        with Live(generate_table(), console=console, refresh_per_second=1) as live:
            while True:
                time.sleep(1)
                live.update(generate_table())
    except KeyboardInterrupt:
        print("\n모니터링을 종료합니다.")

if __name__ == "__main__":
    main()
