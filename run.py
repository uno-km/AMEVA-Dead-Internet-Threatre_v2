import asyncio
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
        result = await asyncio.to_thread(
            subprocess.run, 
            ["docker", "ps", "--format", "{{.Names}}"], 
            capture_output=True, 
            text=True
        )
        running = result.stdout.strip().split("\n")
        
        containers = ["ameva-llm-main", "ameva-llm-god", "ameva-llm-bot-1", "ameva-llm-bot-2", "ameva-llm-bot-3"]
        status = {}
        for c in containers:
            status[c] = "RUNNING" if c in running else "STOPPED"
            
        return {
            "state": state_manager.state.value,
            "checkpoint": state_manager.checkpoint.value,
            "is_command_running": state_manager.is_command_running,
            "last_error": state_manager.last_error_message,
            "containers": status
        }
    except Exception as e:
        logger.error(f"Failed to check docker status: {e}")
        return {
            "state": state_manager.state.value,
            "checkpoint": state_manager.checkpoint.value,
            "is_command_running": state_manager.is_command_running,
            "last_error": str(e),
            "containers": {}
        }

from pydantic import BaseModel

class NewSessionReq(BaseModel):
    inference_mode: str = "sequential"

@app.post("/api/control/new")
async def control_new(req: NewSessionReq = None):
    if state_manager.state != SystemState.IDLE:
        return {"error": "명령어 수행중입니다. 동작 못합니다."}
        
    mode = req.inference_mode if req else "sequential"
    state_manager.set_state(SystemState.RUNNING)
    asyncio.create_task(run_session(inference_mode=mode))
    return {"message": f"New session started (mode: {mode})"}

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
    try:
        # docker-compose.yml의 web-app을 제외한 나머지 서비스들만 구동 (포트 충돌 방지)
        # VRAM 최적화 모드: 초기에는 Dozzle(로그 뷰어)만 시작하고 LLM들은 동적으로 구동/종료
        compose_cmd = [
            "docker", "compose", "-f", "docker/docker-compose.yml", 
            "up", "-d", "dozzle"
        ]
        subprocess.run(compose_cmd, check=True)
        print("[System] 도커 컨테이너 구동 완료.")
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
        except Exception as e:
            print(f"[System ERROR] 도커 컨테이너 종료 중 오류 발생: {e}")
