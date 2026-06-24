import urllib.request
import urllib.parse
import json
import sys
import time

def send_command(cmd, session_id=None):
    url = f"http://localhost:8080/api/control/{cmd}"
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
    url = "http://localhost:8080/api/system/status"
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
    url = "http://localhost:8080/api/system/status"
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
    print("  new [args]     - Start a new session. Available args:")
    print("                     local : Run a single shared LLM model for all bots")
    print("                     mode=<val> : Set model mode (e.g., mode=high)")
    print("                     chat=<val> : Set chat mode (concurrent or sequential)")
    print("                     [!] Example: new local mode=high chat=sequential")
    print("  pause          - Soft pause the current session")
    print("  resume         - Resume a paused session")
    print("  stop           - Force stop the current session")
    print("  restart <post_id> - Restore and continue an old session")
    print("  sre halt       - Emergency system halt")
    print("  sre reconcile <exp_id> - Manually trigger reconciliation verify")
    print("  sre failover <node_id> - Trigger benchmark to check and failover node")
    print("  sre replay <exp_id>    - Run deterministic replay audit")
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
                # 파라미터 파싱 (예: new local mode=high chat=sequential)
                payload = {
                    "inference_mode": "sequential",  # default
                    "model_mode": "standard",        # default
                    "chat_mode": "sequential"        # default
                }
                
                if len(user_input) > 1:
                    for arg in user_input[1:]:
                        if arg == "local":
                            payload["inference_mode"] = "local_single_model"
                        elif arg.startswith("mode="):
                            payload["model_mode"] = arg.split("=")[1]
                        elif arg.startswith("chat="):
                            payload["chat_mode"] = arg.split("=")[1]
                
                url = "http://localhost:8080/api/control/new"
                req = urllib.request.Request(url, method="POST")
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
            elif cmd == "sre":
                if len(user_input) < 2:
                    print("Usage: sre [halt|reconcile|failover|replay]")
                    continue
                sub = user_input[1].lower()
                if sub == "halt":
                    req = urllib.request.Request("http://localhost:8050/api/v1/sre/chaos", method="POST")
                    req.add_header('Content-Type', 'application/json')
                    req.data = json.dumps({"drop_rate": 1.0}).encode('utf-8')
                    try:
                        urllib.request.urlopen(req)
                        print("[SRE] Emergency halt activated: platform requests will be blocked.")
                    except Exception as e:
                        print(f"[SRE Error] Failed to configure chaos: {e}")
                    send_command("stop")
                elif sub == "reconcile":
                    if len(user_input) < 3:
                        print("Usage: sre reconcile <exp_id>")
                        continue
                    exp_id = user_input[2]
                    req = urllib.request.Request("http://localhost:8050/api/v1/federation/reconciliation/verify", method="POST")
                    req.add_header('Content-Type', 'application/json')
                    req.data = json.dumps({"experiment_id": exp_id, "total_accrued_reward": 0.0, "total_charged_fee": 0.0}).encode('utf-8')
                    try:
                        with urllib.request.urlopen(req) as res:
                            res_json = json.loads(res.read().decode('utf-8'))
                            print(f"[SRE Reconcile] Experiment: {res_json.get('experiment_id')}")
                            print(f"Verified: {res_json.get('verified')}, Details: {res_json.get('details')}")
                            print(f"Platform Total Accrued: {res_json.get('platform_accrued')}, Charged: {res_json.get('platform_charged')}")
                    except Exception as e:
                        print(f"[SRE Error] Reconcile verification failed: {e}")
                elif sub == "failover":
                    if len(user_input) < 3:
                        print("Usage: sre failover <node_id>")
                        continue
                    node_id = user_input[2]
                    req = urllib.request.Request("http://localhost:8050/api/v1/sre/benchmark/trigger", method="POST")
                    req.add_header('Content-Type', 'application/json')
                    req.data = json.dumps({"node_id": node_id}).encode('utf-8')
                    try:
                        with urllib.request.urlopen(req) as res:
                            res_json = json.loads(res.read().decode('utf-8'))
                            print(f"[SRE Failover] Node: {node_id} trigger failover benchmark completed.")
                            print(f"Result detail: {res_json.get('result')}")
                    except Exception as e:
                        print(f"[SRE Error] Failover benchmark failed: {e}")
                elif sub == "replay":
                    if len(user_input) < 3:
                        print("Usage: sre replay <exp_id>")
                        continue
                    exp_id = user_input[2]
                    req = urllib.request.Request("http://localhost:8050/api/v1/sre/replay", method="POST")
                    req.add_header('Content-Type', 'application/json')
                    req.data = json.dumps({"experiment_id": exp_id}).encode('utf-8')
                    try:
                        with urllib.request.urlopen(req) as res:
                            res_json = json.loads(res.read().decode('utf-8'))
                            print(f"[SRE Replay] Audit completed for '{exp_id}'. Status: {res_json.get('status')}")
                    except Exception as e:
                        print(f"[SRE Error] Replay failed: {e}")
                else:
                    print(f"Unknown SRE command: {sub}")
            else:
                print(f"Unknown command: {cmd}")
        except KeyboardInterrupt:
            print("\nExiting Remote Controller...")
            sys.exit(0)
        except Exception as e:
            print(f"CLI Error: {e}")

if __name__ == "__main__":
    main()
