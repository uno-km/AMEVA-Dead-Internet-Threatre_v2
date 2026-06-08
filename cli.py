import urllib.request
import urllib.parse
import json
import sys
import time

def send_command(cmd, session_id=None):
    url = f"http://localhost:8050/api/control/{cmd}"
    if session_id:
        url += f"/{session_id}"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if "error" in res_json:
                print(f"[Error] {res_json['error']}")
                return False
            else:
                print(f"[Success] {res_json.get('message', 'OK')}")
                return True
    except Exception as e:
        print(f"[Network Error] Failed to send command to server: {e}")
        return False

def wait_for_state(target_states, timeout=30):
    url = "http://localhost:8050/api/system/status"
    req = urllib.request.Request(url, method="GET")
    start_time = time.time()
    
    if isinstance(target_states, str):
        target_states = [target_states]
        
    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                current_state = res_json.get('global_state')
                if current_state in target_states:
                    return True
        except:
            pass
        time.sleep(1.5)
    return False

def get_status():
    url = "http://localhost:8050/api/system/status"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            print(f"System State: {res_json.get('global_state')} (Checkpoint: {res_json.get('checkpoint')})")
    except Exception as e:
        print(f"[Network Error] Failed to get status from server: {e}")

def main():
    print("========================================")
    print("  AMEVA Orchestrator Remote Controller  ")
    print("========================================")
    print("Commands:")
    print("  run            - Check system status")
    print("  new            - Start a new session")
    print("  pause          - Soft pause the current session")
    print("  resume         - Resume a paused session")
    print("  stop           - Force stop the current session")
    print("  restart <post_id> - Restore and continue an old session")
    print("  exit           - Close this remote controller")
    print("========================================")
    
    while True:
        try:
            user_input = input("Ameva> ").strip().split()
            if not user_input:
                continue
            
            cmd = user_input[0].lower()
            
            if cmd == "exit":
                print("Exiting Remote Controller...")
                sys.exit(0)
            elif cmd == "run":
                get_status()
            elif cmd == "new":
                # 파라미터 파싱 (예: new local, new mode=high)
                payload = {}
                if len(user_input) > 1:
                    if "local" in user_input:
                        payload["inference_mode"] = "local_single_model"
                
                url = "http://localhost:8050/api/control/new"
                req = urllib.request.Request(url, method="POST")
                if payload:
                    data = json.dumps(payload).encode('utf-8')
                    req.add_header('Content-Type', 'application/json')
                    req.data = data
                    
                try:
                    with urllib.request.urlopen(req) as response:
                        res_body = response.read().decode('utf-8')
                        res_json = json.loads(res_body)
                        if "error" in res_json:
                            print(f"[Error] {res_json['error']}")
                        else:
                            print(f"[Success] {res_json.get('message', 'New session started')}")
                            if wait_for_state("RUNNING", 10):
                                print("[완료] 시스템이 가동(RUNNING) 되었습니다!")
                except Exception as e:
                    print(f"[Network Error] Failed to start new session: {e}")
                    
            elif cmd in ["pause", "resume", "stop"]:
                if send_command(cmd):
                    if cmd == "stop":
                        print("진행 중인 발언을 마저 끝내고 안전하게 멈추는 중입니다... (최대 20초 소요)")
                        if wait_for_state("IDLE", 30):
                            print("[완료] 시스템이 안전하게 대기(IDLE) 상태로 전환되었습니다!")
                        else:
                            print("[주의] 종료가 지연되고 있습니다. run 명령어로 상태를 확인하세요.")
                    elif cmd == "pause":
                        print("현재 발언까지만 끝내고 일시정지하는 중입니다... (최대 20초 소요)")
                        if wait_for_state("PAUSED", 30):
                            print("[완료] 시스템이 일시정지(PAUSED) 되었습니다!")
                        else:
                            print("[주의] 일시정지가 지연되고 있습니다. run 명령어로 상태를 확인하세요.")
                    elif cmd == "resume":
                        if wait_for_state("RUNNING", 10):
                            print("[완료] 시스템이 가동(RUNNING) 되었습니다!")
                            
            elif cmd == "restart":
                if len(user_input) > 1 and user_input[1].isdigit():
                    if send_command("restart", user_input[1]):
                        if wait_for_state("RUNNING", 10):
                            print(f"[완료] {user_input[1]}번 글(Post)의 세션 이어하기(RUNNING)를 시작합니다!")
                else:
                    print("Usage: restart <post_id>")
            else:
                print(f"Unknown command: {cmd}")
        except KeyboardInterrupt:
            print("\nExiting Remote Controller...")
            sys.exit(0)
        except Exception as e:
            print(f"CLI Error: {e}")

if __name__ == "__main__":
    main()
