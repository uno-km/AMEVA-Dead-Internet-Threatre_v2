import asyncio
import time
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session as DbSession
import logging

from src.db.database import init_db, get_db
from src.db.models import Session, Post, Comment, BotState
from src.orchestration.runner import run_session, restart_session
from src.orchestration.state_manager import state_manager, SystemState

templates = Jinja2Templates(directory="src/ui/templates")
logger = logging.getLogger("API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. DB 초기화
    init_db()
    logger.info("[System] Database initialized. Waiting in IDLE state.")
    
    yield
    
    logger.info("[System] Shutting down AMEVA-DeadInternetSociety...")
    stop_native_server()

app = FastAPI(title="AMEVA-DeadInternetSociety", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="src/ui/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    메인 게시판 UI 렌더링 (SPA)
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )

@app.get("/api/posts")
async def get_posts(db: DbSession = Depends(get_db)):
    posts = db.query(Post).order_by(Post.id.desc()).all()
    return [{"id": p.id, "title": p.title, "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")} for p in posts]

@app.get("/api/posts/{post_id}")
async def get_post_detail(post_id: int, db: DbSession = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        return {"error": "Post not found"}
        
    session_status = "UNKNOWN"
    session_obj = db.query(Session).filter(Session.id == post.session_id).first()
    if session_obj:
        session_status = session_obj.status

    comments = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.created_at.asc()).all()
    
    comments_data = []
    for c in comments:
        comments_data.append({
            "id": c.id,
            "parent_id": c.parent_id,
            "bot_name": c.bot_name,
            "content": c.content,
            "anger_score": c.anger_score,
            "mentioned_bot": c.mentioned_bot,
            "created_at": c.created_at.strftime("%H:%M:%S")
        })
        
    return {
        "id": post.id,
        "title": post.title,
        "content": post.content,
        "session_status": session_status,
        "created_at": post.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "comments": comments_data
    }

@app.get("/api/bots/state")
async def get_bot_states(db: DbSession = Depends(get_db)):
    import json
    from src.orchestration.runner import calculate_effective_anger
    
    bot_states_db = db.query(BotState).all()
    bot_states = []
    
    # Get latest active session for status
    latest_session = db.query(Session).order_by(Session.id.desc()).first()
    session_status = latest_session.status if latest_session else "UNKNOWN"
    
    for b in bot_states_db:
        try:
            anger_dict = json.loads(b.anger_targets) if b.anger_targets else {}
        except:
            anger_dict = {}
        eff = calculate_effective_anger(anger_dict)
        bot_states.append({
            "bot_name": b.bot_name,
            "persona": b.persona,
            "current_directive": b.current_directive,
            "anger_targets": anger_dict,
            "effective_anger": eff
        })
        
    return {"states": bot_states, "session_status": session_status}

@app.get("/api/lpde/state")
async def get_lpde_states(
    session_id: int | None = Query(default=None),
    db: DbSession = Depends(get_db)
):
    import json
    from src.db.models import CurrentAgentState, Session
    
    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    q = db.query(CurrentAgentState)
    if session_id is not None:
        q = q.filter(CurrentAgentState.session_id == session_id)
        
    lpde_states = q.all()
    results = []
    for s in lpde_states:
        def safe_load(val):
            try:
                return json.loads(val) if val else []
            except:
                return []
                
        results.append({
            "session_id": s.session_id,
            "bot_name": s.bot_name,
            "affect": safe_load(s.affect_json),
            "opinion": safe_load(s.opinion_json),
            "power": safe_load(s.power_json),
            "updated_at": s.updated_at.strftime("%Y-%m-%d %H:%M:%S") if s.updated_at else None
        })
    if not results:
        return {
            "session_id": session_id,
            "message": "No LPDE state yet for this session",
            "lpde_states": []
        }
    return {
        "session_id": session_id,
        "lpde_states": results
    }

@app.get("/api/sessions")
async def get_sessions(db: DbSession = Depends(get_db)):
    from src.db.models import Session
    sessions = db.query(Session).order_by(Session.id.desc()).all()
    return [{"id": s.id, "status": s.status, "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S")} for s in sessions]

@app.get("/api/lpde/bot/{bot_name}/summary")
async def get_bot_inspector_summary(
    bot_name: str,
    session_id: int | None = Query(default=None),
    db: DbSession = Depends(get_db)
):
    import json
    from src.db.models import Session, BotState, CurrentAgentState, AgentStateSnapshot
    from src.orchestration.runner import calculate_effective_anger

    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    # Base legacy state
    bot_state = db.query(BotState).filter(BotState.bot_name == bot_name).first()
    persona = bot_state.persona if bot_state else ""
    current_directive = bot_state.current_directive if bot_state else ""
    try:
        anger_dict = json.loads(bot_state.anger_targets) if bot_state and bot_state.anger_targets else {}
    except:
        anger_dict = {}
    effective_anger = calculate_effective_anger(anger_dict)

    current_state = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == session_id,
        CurrentAgentState.bot_name == bot_name
    ).first()

    def safe_load(val):
        try:
            return json.loads(val) if val else []
        except:
            return []

    def safe_load_dict(val):
        try:
            return json.loads(val) if val else {}
        except:
            return {}

    # Deltas
    snapshots = db.query(AgentStateSnapshot).filter(
        AgentStateSnapshot.session_id == session_id,
        AgentStateSnapshot.bot_name == bot_name
    ).order_by(AgentStateSnapshot.turn_index.desc()).limit(2).all()
    
    deltas = {"affect": [], "opinion": [], "power": []}
    if len(snapshots) >= 2:
        latest_snap = snapshots[0]
        prev_snap = snapshots[1]
        
        def calc_delta(latest_val, prev_val):
            l_list = safe_load(latest_val)
            p_list = safe_load(prev_val)
            res = []
            for l, p in zip(l_list, p_list):
                if isinstance(l, (int, float)) and isinstance(p, (int, float)):
                    val = round(l - p, 3)
                    res.append(val)
                else:
                    res.append(0)
            return res
            
        deltas = {
            "affect": calc_delta(latest_snap.affect_json, prev_snap.affect_json),
            "opinion": calc_delta(latest_snap.opinion_json, prev_snap.opinion_json),
            "power": calc_delta(latest_snap.power_json, prev_snap.power_json)
        }

    # Empty state handling
    if not current_state:
        return {
            "bot_name": bot_name,
            "session_id": session_id,
            "phase": "LPDE_Phase_3",
            "active_dims": ["affect", "opinion", "power"],
            "role_label": "swing_moderate",
            "role_meta": {},
            "conviction": None,
            "flexibility": None,
            "message": "No LPDE state yet for this session",
            "legacy_state": {
                "persona": persona,
                "current_directive": current_directive,
                "effective_anger": effective_anger,
                "anger_targets": anger_dict
            },
            "lpde_tensors": {"affect": [], "opinion": [], "power": []},
            "relation_summary": {},
            "deltas": {"affect": [], "opinion": [], "power": []}
        }

    # opinion_json 차원 정의 (Phase 3):
    # opinion[0] = stance_pole, opinion[1] = conviction, opinion[2] = moral_salience, opinion[3] = flexibility
    lpde_tensors = {
        "affect": safe_load(current_state.affect_json),
        "opinion": safe_load(current_state.opinion_json),
        "power": safe_load(current_state.power_json)
    }
    opinion_vec = lpde_tensors["opinion"]

    from src.core.personality_engine import personality_engine
    relation_summary = personality_engine.get_edges_for_bot(db, session_id, bot_name)

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "updated_at": current_state.updated_at.strftime("%Y-%m-%d %H:%M:%S") if current_state.updated_at else None,
        "phase": "LPDE_Phase_3",
        "active_dims": ["affect", "opinion", "power"],
        # Phase 3: role info
        "role_label": getattr(current_state, "role_label", "swing_moderate"),
        "role_meta": safe_load_dict(getattr(current_state, "role_meta_json", "{}")),
        "conviction": opinion_vec[1] if len(opinion_vec) > 1 else None,
        "flexibility": opinion_vec[3] if len(opinion_vec) > 3 else None,
        "legacy_state": {
            "persona": persona,
            "current_directive": current_directive,
            "effective_anger": effective_anger,
            "anger_targets": anger_dict
        },
        "lpde_tensors": lpde_tensors,
        "relation_summary": relation_summary,
        "deltas": deltas
    }

@app.get("/api/lpde/bot/{bot_name}/detail")
async def get_bot_inspector_detail(
    bot_name: str,
    session_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: DbSession = Depends(get_db)
):
    import json
    from src.db.models import Session, CurrentAgentState, AgentStateSnapshot, EdgeState, InterventionLog

    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    current_state = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == session_id,
        CurrentAgentState.bot_name == bot_name
    ).first()

    def safe_load(val):
        try:
            return json.loads(val) if val else []
        except:
            return []

    def safe_load_dict(val):
        try:
            return json.loads(val) if val else {}
        except:
            return {}

    raw_tensors = {}
    if current_state:
        raw_tensors = {
            "traits": safe_load(current_state.traits_json),
            "states": safe_load(current_state.states_json),
            "affect": safe_load(current_state.affect_json),
            "memory": safe_load(current_state.memory_json),
            "opinion": safe_load(current_state.opinion_json),
            "power": safe_load(current_state.power_json),
            "event_data": safe_load(current_state.event_data_json)
        }

    # Time series (reverse order so oldest first)
    # opinion 차원: [stance_pole, conviction, moral_salience, flexibility]
    # trajectory 좌표 표준: x=stance_pole, y=conviction, z=flexibility
    snapshots = db.query(AgentStateSnapshot).filter(
        AgentStateSnapshot.session_id == session_id,
        AgentStateSnapshot.bot_name == bot_name
    ).order_by(AgentStateSnapshot.turn_index.desc()).limit(limit).all()
    
    time_series = []
    recent_events = []
    for snap in reversed(snapshots):
        opinion_vec = safe_load(snap.opinion_json)
        time_series.append({
            "turn_index": snap.turn_index,
            "affect": safe_load(snap.affect_json),
            "opinion": opinion_vec,
            "power": safe_load(snap.power_json),
            "role_label": getattr(snap, "role_label", "swing_moderate"),
            # Phase 3 trajectory coords (standardized axes)
            "x": opinion_vec[0] if len(opinion_vec) > 0 else 0.0,  # stance_pole
            "y": opinion_vec[1] if len(opinion_vec) > 1 else 0.0,  # conviction
            "z": opinion_vec[3] if len(opinion_vec) > 3 else 0.0,  # flexibility
        })
        
        event_data = safe_load_dict(snap.event_data_json)
        if event_data and isinstance(event_data, dict) and event_data.get("events"):
            recent_events.append({
                "turn_index": snap.turn_index,
                "events": event_data.get("events"),
                "speaker": event_data.get("speaker"),
                "target": event_data.get("target"),
                "intensity": event_data.get("intensity", 0.0)
            })

    # Edges
    edges = db.query(EdgeState).filter(
        EdgeState.session_id == session_id,
        (EdgeState.source_bot == bot_name) | (EdgeState.target_bot == bot_name)
    ).all()
    
    edges_data = [{"source": e.source_bot, "target": e.target_bot, "relation": safe_load_dict(e.relation_json)} for e in edges]

    # Interventions
    interventions = db.query(InterventionLog).filter(
        InterventionLog.session_id == session_id,
        InterventionLog.target_bot == bot_name
    ).order_by(InterventionLog.turn_index.desc()).all()
    interventions_data = [{"turn_index": i.turn_index, "kind": i.kind, "delta": safe_load_dict(i.delta_json), "reason": i.reason} for i in interventions]

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "raw_tensors": raw_tensors,
        "time_series": time_series,
        "edges": edges_data,
        "interventions": interventions_data,
        "recent_events": recent_events
    }

@app.get("/api/system/status")
async def get_system_status():
    import subprocess
    try:
        if os.name == 'nt':
            try:
                result = await asyncio.to_thread(
                    subprocess.run, 
                    ["docker", "ps", "--format", "{{.Names}}"], 
                    capture_output=True, 
                    text=True
                )
                running = result.stdout.strip().split("\n")
            except FileNotFoundError:
                running = []
        else:
            try:
                result = await asyncio.to_thread(
                    subprocess.run, 
                    ["docker", "ps", "--format", "{{.Names}}"], 
                    capture_output=True, 
                    text=True
                )
                running = result.stdout.strip().split("\n")
            except FileNotFoundError:
                running = []
        
        containers = ["ameva-llm-main", "ameva-llm-god", "ameva-llm-bot-1", "ameva-llm-bot-2", "ameva-llm-bot-3"]
        status = {}
        for c in containers:
            status[c] = "RUNNING" if c in running else "STOPPED"
            
        return {
            "state": state_manager.state.value,
            "checkpoint": state_manager.checkpoint.value,
            "is_command_running": state_manager.is_command_running,
            "last_error": state_manager.last_error_message,
            "current_activity": getattr(state_manager, "current_activity", "대기 중..."),
            "containers": status
        }
    except Exception as e:
        logger.error(f"Failed to check docker status: {e}")
        return {
            "state": state_manager.state.value,
            "checkpoint": state_manager.checkpoint.value,
            "is_command_running": state_manager.is_command_running,
            "last_error": str(e),
            "current_activity": getattr(state_manager, "current_activity", "대기 중..."),
            "containers": {}
        }

from pydantic import BaseModel

class NewSessionReq(BaseModel):
    inference_mode: str = "sequential"
    model_mode: str = "standard"
    chat_mode: str = "sequential"

import os
import subprocess
import yaml

startup_status = {"total": 0, "completed": 0, "current_task": "Waiting...", "is_running": False}

import psutil

native_server_process = None

def kill_process_on_port(port: int):
    import psutil
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            connections = proc.connections(kind='inet')
            for conn in connections:
                if conn.laddr.port == port:
                    logger.info(f"[KILL PORT] Found process {proc.info['name']} (PID {proc.info['pid']}) on port {port}. Terminating...")
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        logger.warning(f"[KILL PORT] Process {proc.info['pid']} did not terminate. Killing...")
                        proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
        except Exception as e:
            logger.warning(f"[KILL PORT] Error checking process: {e}")

def get_native_llama_cmd(server_path: str, model_name: str, hardware_mode: str) -> list:
    import sys
    import shutil
    
    model_path = os.path.join("models", "llm", model_name)
    if not os.path.exists(model_path):
        parent_path = os.path.join("..", "models", "llm", model_name)
        if os.path.exists(parent_path):
            model_path = parent_path
            
    # If the user provided just "llama-server" or "자동 (내장 서버)" and it's not in PATH, use python -m llama_cpp.server
    cmd = []
    if (server_path == "llama-server" or server_path == "자동 (내장 서버)") and shutil.which("llama-server") is None:
        cmd = [sys.executable, "-m", "llama_cpp.server"]
    else:
        cmd = [server_path]
        
    cmd.extend([
        "--model", model_path,
        "--n_ctx", "4096",
        "--host", "0.0.0.0",
        "--port", "8101"
    ])
    
    hw = hardware_mode
    if hw == "gpu":
        hw = get_recommended_gpu_backend()
    
    if hw in ["cuda", "vulkan"]:
        cmd.extend(["--n_gpu_layers", "99"])
        
    return cmd

def start_native_server(server_path: str, model_name: str, hardware_mode: str):
    global native_server_process
    stop_native_server()
    
    # Ensure port 8101 is clean before starting
    kill_process_on_port(8101)
    
    cmd = get_native_llama_cmd(server_path, model_name, hardware_mode)
    logger.info(f"[NATIVE] Spawning server command: {' '.join(cmd)}")
    
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
            
        native_server_process = subprocess.Popen(
            cmd,
            startupinfo=startupinfo,
            env=env
        )
        logger.info(f"[NATIVE] Server process started with PID {native_server_process.pid}")
    except FileNotFoundError:
        logger.error(f"[NATIVE ERROR] Failed to start native server: '{server_path}' not found. Please pip install llama-cpp-python[server] or set correct path.")
        raise RuntimeError(f"'{server_path}' (또는 llama-cpp-python[server]) 파일을 찾을 수 없습니다. (환경변수 PATH 확인 또는 올바른 경로 입력 필요)")
    except Exception as e:
        logger.error(f"[NATIVE ERROR] Failed to start native server: {e}")
        raise

def stop_native_server():
    global native_server_process
    if native_server_process:
        logger.info(f"[NATIVE] Terminating native server process {native_server_process.pid}")
        try:
            native_server_process.terminate()
            native_server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("[NATIVE] Process did not terminate, killing...")
            try:
                native_server_process.kill()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[NATIVE] Exception terminating process: {e}")
        native_server_process = None
    
    # Force double-check kill on 8101 port
    kill_process_on_port(8101)

def get_recommended_gpu_backend() -> str:
    try:
        import subprocess
        # Get GPU name using nvidia-smi
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True
        )
        gpu_name = result.stdout.strip()
        logger.info(f"[GPU DETECTION] Detected GPU: {gpu_name}")
        # If it's a GTX card, recommend vulkan
        if "GTX" in gpu_name:
            logger.info("[GPU DETECTION] GTX card detected. Recommending Vulkan.")
            return "vulkan"
        else:
            logger.info("[GPU DETECTION] RTX or other card detected. Recommending CUDA.")
            return "cuda"
    except Exception as e:
        logger.warning(f"[GPU DETECTION] Failed to detect GPU name: {e}. Defaulting to vulkan.")
        return "vulkan"

@app.get("/api/system/setup-info")
async def get_setup_info():
    hardware_status = {"cpu": True, "gpu_found": False, "cuda_available": False, "recommended_gpu_backend": "cpu", "details": "CPU Only"}
    try:
        try:
            result = await asyncio.to_thread(subprocess.run, ["nvidia-smi"], capture_output=True, text=True)
            if result.returncode == 0:
                hardware_status["gpu_found"] = True
                hardware_status["cuda_available"] = True
                backend = await asyncio.to_thread(get_recommended_gpu_backend)
                hardware_status["recommended_gpu_backend"] = backend
                if backend == "vulkan":
                    hardware_status["details"] = "GPU 가속 가능 (GTX 계열 감지: Vulkan 권장)"
                else:
                    hardware_status["details"] = "GPU 가속 가능 (CUDA 권장)"
            else:
                hardware_status["details"] = "GPU Not Found (nvidia-smi failed)"
        except FileNotFoundError:
            hardware_status["details"] = "GPU Not Found (nvidia-smi not in PATH)"
    except Exception:
        hardware_status["details"] = "GPU Not Found (nvidia-smi not in PATH)"

    # 모델 파일 목록 읽기 (.gguf)
    models_dir = os.path.join("models", "llm")
    models = []
    parent_models_dir = os.path.join("..", "models", "llm") # docker-compose 경로상 ../../models/llm
    
    check_dir = models_dir
    if not os.path.exists(check_dir) and os.path.exists(parent_models_dir):
        check_dir = parent_models_dir

    if os.path.exists(check_dir):
        for f in os.listdir(check_dir):
            if f.endswith(".gguf"):
                models.append(f)
                
    return {
        "hardware": hardware_status,
        "models": models
    }

@app.get("/api/system/browse-file")
async def browse_file():
    import tkinter as tk
    from tkinter import filedialog
    import asyncio
    
    def _open_dialog():
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.askopenfilename(
            title="Select llama-server executable",
            filetypes=[("Executables", "*.exe"), ("All Files", "*.*")]
        )
        root.destroy()
        return file_path
        
    try:
        path = await asyncio.to_thread(_open_dialog)
        return {"path": path if path else ""}
    except Exception as e:
        logger.error(f"Failed to open file dialog: {e}")
        return {"error": str(e), "path": ""}

@app.get("/api/system/startup-progress")
async def get_startup_progress():
    return startup_status

class SetupStartReq(BaseModel):
    inference_mode: str = "sequential"
    hardware_mode: str = "cpu"
    model_main: str = ""
    model_god: str = ""
    model_bot1: str = ""
    model_bot2: str = ""
    model_bot3: str = ""
    llama_server_path: Optional[str] = "llama-server"

async def do_startup_sequence(req: SetupStartReq):
    global startup_status
    try:
        if req.inference_mode == "local_native":
            startup_status["total"] = 1
            state_manager.current_activity = "로컬 llama-server 프로세스 실행 중..."
            startup_status["current_task"] = "Starting native llama-server..."
            
            # Start native server
            await asyncio.to_thread(
                start_native_server,
                server_path=req.llama_server_path or "llama-server",
                model_name=req.model_main,
                hardware_mode=req.hardware_mode
            )
            
            # Wait for ready url
            from src.orchestration.runner import wait_for_http_ready
            ready_url = "http://localhost:8101/v1/models"
            
            start_t = time.time()
            ready = False
            while time.time() - start_t < 300:
                if native_server_process and native_server_process.poll() is not None:
                    raise RuntimeError(f"로컬 파이썬 서버(llama_cpp.server)가 실행 직후 종료되었습니다 (종료 코드: {native_server_process.returncode}). llama-cpp-python이 설치되지 않았을 수 있습니다. run.bat를 실행해 종속성을 설치해 주세요.")
                
                # Check for 2 seconds at a time
                if await wait_for_http_ready(ready_url, timeout=2, interval=1):
                    ready = True
                    break
                    
            if not ready:
                raise RuntimeError("로컬 파이썬 서버(llama_cpp.server) 기동 실패 (헬스체크 타임아웃: 300초 경과)")
                
            startup_status["completed"] = 1
            state_manager.current_activity = "로컬 llama-server 구동 완료. 세션을 준비 중..."
            startup_status["current_task"] = "Startup complete. Preparing session..."
            await asyncio.sleep(1)
            startup_status["is_running"] = False
            
            state_manager.set_state(SystemState.RUNNING)
            asyncio.create_task(run_session(inference_mode=req.inference_mode))
            return

        state_manager.current_activity = "도커 데몬 상태 확인 중..."
        startup_status["current_task"] = "Checking Docker daemon..."
        try:
            subprocess.run(["docker", "info"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            state_manager.current_activity = "도커 데스크탑 실행 중 (최대 1분 소요)..."
            startup_status["current_task"] = "Starting Docker Desktop... (Please wait up to 1 min)"
            docker_path = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
            if os.path.exists(docker_path):
                subprocess.Popen([docker_path])
                docker_ready = False
                for _ in range(45): # wait up to 90 seconds
                    await asyncio.sleep(2)
                    try:
                        subprocess.run(["docker", "info"], check=True, capture_output=True)
                        docker_ready = True
                        break
                    except Exception:
                        pass
                if not docker_ready:
                    raise Exception("Docker Desktop took too long to start. Please start it manually.")
            else:
                raise Exception("Docker Desktop is not running and could not be found at C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe.")

        state_manager.current_activity = "기존 컨테이너 종료 중..."
        startup_status["current_task"] = "Stopping existing containers..."
        cmd_down = ["docker", "compose", "-f", "docker/docker-compose.yml"]
        if os.path.exists("docker/docker-compose.override.yml"):
            cmd_down.extend(["-f", "docker/docker-compose.override.yml"])
        cmd_down.append("down")
        try:
            await asyncio.to_thread(subprocess.run, cmd_down, capture_output=True)
        except FileNotFoundError:
            pass

        containers_to_start = ["dozzle"]
        if req.inference_mode == "parallel":
            containers_to_start.extend(["ameva-llm-main", "ameva-llm-god", "ameva-llm-bot-1", "ameva-llm-bot-2", "ameva-llm-bot-3"])
        elif req.inference_mode == "local_single_model":
            containers_to_start.extend(["ameva-llm-main"])
            
        startup_status["total"] = len(containers_to_start)
        
        for i, c in enumerate(containers_to_start):
            state_manager.current_activity = f"[{i+1}/{len(containers_to_start)}] 도커 컨테이너 {c} 구동 중..."
            startup_status["current_task"] = f"[{i+1}/{len(containers_to_start)}] Starting {c}..."
            svc_name = c.replace("ameva-", "") if "ameva-" in c else c
            cmd_up = ["docker", "compose", "-f", "docker/docker-compose.yml", "-f", "docker/docker-compose.override.yml", "up", "-d", svc_name]
            try:
                await asyncio.to_thread(subprocess.run, cmd_up, capture_output=True)
            except FileNotFoundError:
                raise RuntimeError("Docker가 설치되어 있지 않거나 PATH에 없습니다.")
            startup_status["completed"] = i + 1
            await asyncio.sleep(0.5)
            
        state_manager.current_activity = "도커 컨테이너 구동 완료. 세션을 준비 중..."
        startup_status["current_task"] = "Startup complete. Preparing session..."
        await asyncio.sleep(1)
        startup_status["is_running"] = False
        
        state_manager.set_state(SystemState.RUNNING)
        asyncio.create_task(run_session(inference_mode=req.inference_mode))
    except Exception as e:
        logger.error(f"Startup error: {e}")
        state_manager.current_activity = f"초기화 에러: {str(e)}"
        startup_status["current_task"] = f"Error: {str(e)}"
        startup_status["is_running"] = False
        state_manager.push_event("ERROR", {"message": f"Startup failed: {str(e)}"})
        state_manager.set_state(SystemState.ERROR)

@app.post("/api/control/setup_and_start")
async def setup_and_start(req: SetupStartReq):
    if state_manager.state != SystemState.IDLE:
        return {"error": "System is not in IDLE state."}
        
    state_manager.set_state(SystemState.RUNNING)
    state_manager.current_activity = "설정 파일 구성 중..."
    state_manager.inference_mode = req.inference_mode
    
    # Save parameters for self-healing
    state_manager.llama_server_path = req.llama_server_path or "llama-server"
    state_manager.model_main = req.model_main
    state_manager.hardware_mode = req.hardware_mode
    
    startup_status["is_running"] = True
    startup_status["total"] = 5
    startup_status["completed"] = 0
    startup_status["current_task"] = "Generating configurations..."
    
    override = {
        "version": "3.8",
        "services": {}
    }
    
    services = {
        "llm-main": req.model_main,
        "llm-god": req.model_god,
        "llm-bot-1": req.model_bot1,
        "llm-bot-2": req.model_bot2,
        "llm-bot-3": req.model_bot3
    }
    
    # Resolve 'gpu' to recommended backend
    hw_mode = req.hardware_mode
    if hw_mode == "gpu":
        hw_mode = get_recommended_gpu_backend()
        logger.info(f"[SETUP] Resolved hardware_mode 'gpu' to '{hw_mode}'")
    
    for svc, model in services.items():
        if not model: continue
        svc_config = {
            "command": f"-m /models/llm/{model} -c 4096 --host 0.0.0.0 --port 8080"
        }
        if hw_mode == "cuda":
            svc_config["image"] = "ghcr.io/ggml-org/llama.cpp:server-cuda"
            svc_config["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [
                            {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
                        ]
                    }
                }
            }
        elif hw_mode == "vulkan":
            svc_config["image"] = "ghcr.io/ggml-org/llama.cpp:server-vulkan"
            svc_config["deploy"] = {
                "resources": {
                    "reservations": {
                        "devices": [
                            {"driver": "nvidia", "count": "all", "capabilities": ["gpu"]}
                        ]
                    }
                }
            }
        override["services"][svc] = svc_config
        
    try:
        with open("docker/docker-compose.override.yml", "w", encoding="utf-8") as f:
            yaml.dump(override, f)
    except Exception as e:
        logger.error(f"Failed to write override: {e}")
        
    asyncio.create_task(do_startup_sequence(req))
    return {"message": "Setup and startup sequence initiated"}

@app.post("/api/control/new")
async def control_new(req: NewSessionReq = None):
    if state_manager.state != SystemState.IDLE:
        return {"error": "명령어 수행중입니다. 동작 못합니다."}
        
    inf_mode = req.inference_mode if req else "sequential"
    mod_mode = req.model_mode if req else "standard"
    ch_mode = req.chat_mode if req else "sequential"
    
    state_manager.set_state(SystemState.RUNNING)
    asyncio.create_task(run_session(inference_mode=inf_mode))
    return {"message": f"New session started (inference: {inf_mode}, model: {mod_mode}, chat: {ch_mode})"}

@app.post("/api/control/pause")
async def control_pause():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No running session found."}
    if state_manager.state in [SystemState.PAUSING, SystemState.PAUSED]:
        return {"error": "Session is already pausing or paused."}
    state_manager.set_state(SystemState.PAUSING)
    return {"message": "Pausing session..."}

@app.post("/api/control/resume")
async def control_resume():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No active session found. Please start a new session or restart an existing one."}
    if state_manager.state == SystemState.RUNNING:
        return {"error": "Session is already running."}
    state_manager.set_state(SystemState.RUNNING)
    return {"message": "Session resumed"}

@app.post("/api/control/stop")
async def control_stop():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No running session found."}
    state_manager.set_state(SystemState.STOPPING)
    return {"message": "Stopping session..."}

@app.post("/api/control/restart/{post_id}")
async def control_restart(post_id: int, db: DbSession = Depends(get_db)):
    if state_manager.state != SystemState.IDLE:
        return {"error": "System is currently busy processing another command."}
        
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        return {"error": f"Post #{post_id} not found."}
        
    session_id = post.session_id
    state_manager.set_state(SystemState.RUNNING)
    asyncio.create_task(restart_session(session_id))
    return {"message": f"Restarting post {post_id} (Session {session_id})"}

@app.get("/api/lpde/bot/{bot_name}/trajectory")
async def get_bot_trajectory(
    bot_name: str,
    session_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: DbSession = Depends(get_db)
):
    """
    Phase 3: 봇의 3D 입장 궤적(trajectory)을 반환.
    
    좌표 표준 (3D 시각화 Three.js 연동 대비):
      x = stance_pole   : opinion[0], 논쟁 축 방향 [-1.0 ~ +1.0]
      y = conviction    : opinion[1], 입장 확신도 [0.0 ~ 1.0]
      z = flexibility   : opinion[3], 유연성 [0.0 ~ 1.0]
    """
    import json
    from src.db.models import Session, AgentStateSnapshot

    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    def safe_load(val):
        try:
            return json.loads(val) if val else []
        except:
            return []

    snapshots = db.query(AgentStateSnapshot).filter(
        AgentStateSnapshot.session_id == session_id,
        AgentStateSnapshot.bot_name == bot_name
    ).order_by(AgentStateSnapshot.turn_index.asc()).limit(limit).all()

    points = []
    for snap in snapshots:
        opinion_vec = safe_load(snap.opinion_json)
        affect_vec = safe_load(snap.affect_json)
        points.append({
            "turn_index": snap.turn_index,
            "x": opinion_vec[0] if len(opinion_vec) > 0 else 0.0,   # stance_pole
            "y": opinion_vec[1] if len(opinion_vec) > 1 else 0.0,   # conviction
            "z": opinion_vec[3] if len(opinion_vec) > 3 else 0.0,   # flexibility
            "arousal": affect_vec[1] if len(affect_vec) > 1 else 0.0,
            "role_label": getattr(snap, "role_label", "swing_moderate"),
        })

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "axis_definition": {
            "x": "stance_pole [-1.0 ~ +1.0]",
            "y": "conviction [0.0 ~ 1.0]",
            "z": "flexibility [0.0 ~ 1.0]"
        },
        "points": points
    }

if __name__ == "__main__":
    import uvicorn
    import subprocess
    import os
    
    print("[System] 자동 실행: 도커 컨테이너(Dozzle 및 AI 봇들)를 시작합니다...")
    # docker-compose.yml의 web-app을 제외한 나머지 서비스들만 구동 (포트 충돌 방지)
    # VRAM 최적화 모드: 초기에는 Dozzle(로그 뷰어)만 시작하고 LLM들은 동적으로 구동/종료
    compose_cmd = [
        "docker", "compose", "-f", "docker/docker-compose.yml", 
        "up", "-d", "dozzle"
    ]
    try:
        subprocess.run(compose_cmd, check=True)
        print("[System] 도커 컨테이너 구동 완료.")
    except FileNotFoundError:
        print("[System ERROR] Docker가 설치되어 있지 않거나 환경변수 PATH에 없습니다. (도커 없이 로컬 모드에서 실행 가능합니다)")
    except Exception as e:
        print(f"[System ERROR] 도커 컨테이너를 시작하는 중 오류 발생: {e}")
        print("[System] 'docker compose up -d' 명령어를 직접 확인해주세요.")

    try:
        print("[System] 로컬 웹 서버를 시작합니다...")
        uvicorn.run("run:app", host="0.0.0.0", port=8050, reload=False)
    finally:
        print("\n[System] 서버 종료 감지: 모든 도커 컨테이너를 안전하게 끕니다 (docker compose down)...")
        try:
            subprocess.run(["docker", "compose", "-f", "docker/docker-compose.yml", "down"], check=True)
            print("[System] 도커 컨테이너 종료 완료.")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[System ERROR] 도커 컨테이너 종료 중 오류 발생: {e}")
        stop_native_server()
