import json
import logging
import asyncio
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DbSession
from pydantic import BaseModel

from app.web.database import get_db
from app.web.models import Session, Post, Comment, BotState, CurrentAgentState, AgentStateSnapshot, EdgeState, InterventionLog, Board
from app.services.state_manager import state_manager, SystemState, Checkpoint

logger = logging.getLogger("WebRouter")
router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")

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

def calculate_effective_anger(anger_dict: dict) -> float:
    import math
    if not anger_dict or not isinstance(anger_dict, dict):
        return 0.0
    sum_sq = 0.0
    for val in anger_dict.values():
        try:
            num = float(val)
            sum_sq += num ** 2
        except:
            continue
    return math.sqrt(sum_sq)

# -----------------------------------------------------------------
# HTML Page Routes
# -----------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    메인 게시판 UI 렌더링 (SPA)
    """
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )

# -----------------------------------------------------------------
# REST API: Posts & Comments (Pure Forum API)
# -----------------------------------------------------------------

@router.get("/api/posts")
async def get_posts(db: DbSession = Depends(get_db)):
    posts = db.query(Post).order_by(Post.id.desc()).all()
    return [{"id": p.id, "title": p.title, "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")} for p in posts]

@router.get("/api/posts/{post_id}")
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

class CreatePostReq(BaseModel):
    title: str
    content: str
    bot_name: str = "SYSTEM"

@router.post("/api/posts")
async def create_post(req: CreatePostReq, db: DbSession = Depends(get_db)):
    latest_session = db.query(Session).order_by(Session.id.desc()).first()
    session_id = latest_session.id if latest_session else 1
    
    # default board check
    board = db.query(Board).first()
    board_id = board.id if board else 1
    
    post = Post(
        board_id=board_id,
        session_id=session_id,
        title=req.title,
        content=req.content
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"message": "Post created successfully", "id": post.id}

class CreateCommentReq(BaseModel):
    bot_name: str
    content: str
    parent_id: Optional[int] = None
    anger_score: Optional[int] = 0
    mentioned_bot: Optional[str] = None

@router.post("/api/posts/{post_id}/comments")
async def create_comment(post_id: int, req: CreateCommentReq, db: DbSession = Depends(get_db)):
    comment = Comment(
        post_id=post_id,
        parent_id=req.parent_id,
        bot_name=req.bot_name,
        content=req.content,
        anger_score=req.anger_score or 0,
        mentioned_bot=req.mentioned_bot
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    
    # Broadcast or trigger state updates if necessary, but keep it loose!
    return {"success": True, "id": comment.id}

# -----------------------------------------------------------------
# REST API: Boards Management (DC Inside style)
# -----------------------------------------------------------------

@router.get("/api/boards")
async def get_boards(db: DbSession = Depends(get_db)):
    boards = db.query(Board).all()
    return [{"name": b.name, "description": b.description, "board_type": b.board_type} for b in boards]

@router.get("/api/boards/{board_name}/posts")
async def get_board_posts(board_name: str, db: DbSession = Depends(get_db)):
    board = db.query(Board).filter(Board.name == board_name).first()
    if not board:
        return []
    posts = db.query(Post).filter(Post.board_id == board.id).order_by(Post.id.desc()).all()
    return [{
        "id": p.id,
        "board_seq_id": p.board_seq_id,
        "title": p.title,
        "created_at": p.created_at.strftime("%Y-%m-%d %H:%M:%S")
    } for p in posts]

class CreateBoardPostReq(BaseModel):
    title: str
    content: str
    bot_name: Optional[str] = "USER"

@router.post("/api/boards/{board_name}/posts")
async def create_board_post(board_name: str, req: CreateBoardPostReq, db: DbSession = Depends(get_db)):
    board = db.query(Board).filter(Board.name == board_name).first()
    if not board:
        return {"success": False, "error": "Board not found"}
    
    latest_session = db.query(Session).order_by(Session.id.desc()).first()
    session_id = latest_session.id if latest_session else 1

    # Calculate board_seq_id
    max_seq = db.query(Post).filter(Post.board_id == board.id).count()
    
    post = Post(
        board_id=board.id,
        board_seq_id=max_seq + 1,
        session_id=session_id,
        title=req.title,
        content=req.content
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"success": True, "id": post.id}

@router.get("/api/nodes/active")
async def get_active_nodes(db: DbSession = Depends(get_db)):
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    nodes = [
        {"bot_name": "bot_1", "hardware_mode": "CPU", "current_activity": getattr(state_manager, "current_activity", "Idle"), "last_seen": now_str},
        {"bot_name": "bot_2", "hardware_mode": "CPU", "current_activity": getattr(state_manager, "current_activity", "Idle"), "last_seen": now_str},
        {"bot_name": "bot_3", "hardware_mode": "CPU", "current_activity": getattr(state_manager, "current_activity", "Idle"), "last_seen": now_str}
    ]
    return {
        "active_count": 3,
        "nodes": nodes
    }

# -----------------------------------------------------------------
# REST API: Agents & LPDE Stats (Simulation API)
# -----------------------------------------------------------------

@router.get("/api/bots/state")
async def get_bot_states(db: DbSession = Depends(get_db)):
    bot_states_db = db.query(BotState).all()
    bot_states = []
    
    latest_session = db.query(Session).order_by(Session.id.desc()).first()
    session_status = latest_session.status if latest_session else "UNKNOWN"
    
    for b in bot_states_db:
        try:
            anger_dict = json.loads(b.anger_targets) if b.anger_targets else {}
        except:
            anger_dict = {}
        eff = calculate_effective_anger(anger_dict)
        
        role_label = "swing_moderate"
        opinion = [0.0, 0.0, 0.0, 0.0]
        if latest_session:
            curr_state = db.query(CurrentAgentState).filter(
                CurrentAgentState.session_id == latest_session.id,
                CurrentAgentState.bot_name == b.bot_name
            ).first()
            if curr_state:
                role_label = curr_state.role_label or "swing_moderate"
                opinion = safe_load(curr_state.opinion_json)
                if not opinion or not isinstance(opinion, list):
                    opinion = [0.0, 0.0, 0.0, 0.0]
                    
        bot_states.append({
            "bot_name": b.bot_name,
            "persona": b.persona,
            "current_directive": b.current_directive,
            "anger_targets": anger_dict,
            "effective_anger": eff,
            "role_label": role_label,
            "opinion": opinion
        })
        
    return {"states": bot_states, "session_status": session_status}

@router.get("/api/lpde/state")
async def get_lpde_states(
    session_id: int | None = Query(default=None),
    db: DbSession = Depends(get_db)
):
    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    q = db.query(CurrentAgentState)
    if session_id is not None:
        q = q.filter(CurrentAgentState.session_id == session_id)
        
    lpde_states = q.all()
    results = []
    for s in lpde_states:
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

@router.get("/api/sessions")
async def get_sessions(db: DbSession = Depends(get_db)):
    sessions = db.query(Session).order_by(Session.id.desc()).all()
    return [{"id": s.id, "status": s.status, "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S")} for s in sessions]

class CreateSessionReq(BaseModel):
    status: str = "ACTIVE"
    reason: Optional[str] = None

@router.post("/api/sessions")
async def create_session(req: CreateSessionReq, db: DbSession = Depends(get_db)):
    session = Session(status=req.status, reason=req.reason)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "status": session.status}

class UpdateSessionReq(BaseModel):
    status: str
    reason: Optional[str] = None

@router.post("/api/sessions/{session_id}/update")
async def update_session_route(session_id: int, req: UpdateSessionReq, db: DbSession = Depends(get_db)):
    session = db.query(Session).filter(Session.id == session_id).first()
    if session:
        session.status = req.status
        if req.reason:
            session.reason = req.reason
        if req.status != "ACTIVE":
            from datetime import datetime
            session.closed_at = datetime.now()
        db.commit()
        return {"message": "Session updated successfully"}
    return {"error": "Session not found"}

class UpdateLpdeReq(BaseModel):
    session_id: int
    turn_index: int
    bot_name: str
    event_data: Optional[dict] = None

@router.post("/api/lpde/update")
async def update_lpde_state(req: UpdateLpdeReq, db: DbSession = Depends(get_db)):
    from app.core.personality_engine import personality_engine
    personality_engine.update_fast_state(
        db, req.session_id, req.bot_name, req.turn_index, req.event_data
    )
    return {"message": "LPDE state updated successfully"}

class InitLpdeReq(BaseModel):
    session_id: int
    role_triplet: Optional[dict] = None

@router.post("/api/lpde/initialize")
async def initialize_lpde_states(req: InitLpdeReq, db: DbSession = Depends(get_db)):
    from app.core.personality_engine import personality_engine
    personality_engine.initialize_session_states(db, req.session_id, req.role_triplet)
    return {"message": "LPDE session states initialized"}

class UpdateBotStateReq(BaseModel):
    bot_name: str
    anger_targets: dict

@router.post("/api/bots/update_anger")
async def update_bot_anger(req: UpdateBotStateReq, db: DbSession = Depends(get_db)):
    bot_state = db.query(BotState).filter(BotState.bot_name == req.bot_name).first()
    if bot_state:
        bot_state.anger_targets = json.dumps(req.anger_targets, ensure_ascii=False)
        db.commit()
        return {"message": f"Anger targets updated for {req.bot_name}"}
    return {"error": "Bot state not found"}

@router.get("/api/lpde/bot/{bot_name}/summary")
async def get_bot_inspector_summary(
    bot_name: str,
    session_id: int | None = Query(default=None),
    db: DbSession = Depends(get_db)
):
    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

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
                    res.append(round(l - p, 3))
                else:
                    res.append(0)
            return res
            
        deltas = {
            "affect": calc_delta(latest_snap.affect_json, prev_snap.affect_json),
            "opinion": calc_delta(latest_snap.opinion_json, prev_snap.opinion_json),
            "power": calc_delta(latest_snap.power_json, prev_snap.power_json)
        }

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

    lpde_tensors = {
        "affect": safe_load(current_state.affect_json),
        "opinion": safe_load(current_state.opinion_json),
        "power": safe_load(current_state.power_json)
    }
    opinion_vec = lpde_tensors["opinion"]

    from app.core.personality_engine import personality_engine
    relation_summary = personality_engine.get_edges_for_bot(db, session_id, bot_name)

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "updated_at": current_state.updated_at.strftime("%Y-%m-%d %H:%M:%S") if current_state.updated_at else None,
        "phase": "LPDE_Phase_3",
        "active_dims": ["affect", "opinion", "power"],
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

@router.get("/api/lpde/bot/{bot_name}/detail")
async def get_bot_inspector_detail(
    bot_name: str,
    session_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: DbSession = Depends(get_db)
):
    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

    bot_state = db.query(BotState).filter(BotState.bot_name == bot_name).first()
    persona = bot_state.persona if bot_state else ""
    current_directive = bot_state.current_directive if bot_state else ""

    current_state = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == session_id,
        CurrentAgentState.bot_name == bot_name
    ).first()

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
            "x": opinion_vec[0] if len(opinion_vec) > 0 else 0.0,
            "y": opinion_vec[1] if len(opinion_vec) > 1 else 0.0,
            "z": opinion_vec[3] if len(opinion_vec) > 3 else 0.0,
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

    edges = db.query(EdgeState).filter(
        EdgeState.session_id == session_id,
        (EdgeState.source_bot == bot_name) | (EdgeState.target_bot == bot_name)
    ).all()
    
    edges_data = [{"source": e.source_bot, "target": e.target_bot, "relation": safe_load_dict(e.relation_json)} for e in edges]

    interventions = db.query(InterventionLog).filter(
        InterventionLog.session_id == session_id,
        InterventionLog.target_bot == bot_name
    ).order_by(InterventionLog.turn_index.desc()).all()
    interventions_data = [{"turn_index": i.turn_index, "kind": i.kind, "delta": safe_load_dict(i.delta_json), "reason": i.reason} for i in interventions]

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "persona": persona,
        "current_directive": current_directive,
        "raw_tensors": raw_tensors,
        "time_series": time_series,
        "edges": edges_data,
        "interventions": interventions_data,
        "recent_events": recent_events
    }

@router.get("/api/lpde/bot/{bot_name}/trajectory")
async def get_bot_trajectory(
    bot_name: str,
    session_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: DbSession = Depends(get_db)
):
    if session_id is None:
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        session_id = latest_session.id if latest_session else None

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
            "x": opinion_vec[0] if len(opinion_vec) > 0 else 0.0,
            "y": opinion_vec[1] if len(opinion_vec) > 1 else 0.0,
            "z": opinion_vec[3] if len(opinion_vec) > 3 else 0.0,
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

# -----------------------------------------------------------------
# REST API: Simulation Control & System Status (Sim API)
# -----------------------------------------------------------------

@router.get("/api/system/status")
async def get_system_status():
    """
    도커가 제거되었으므로 더미 컨테이너 상태와 실제 시스템 상태만 보고
    """
    return {
        "state": state_manager.state.value,
        "checkpoint": state_manager.checkpoint.value,
        "is_command_running": state_manager.is_command_running,
        "last_error": state_manager.last_error_message,
        "current_activity": getattr(state_manager, "current_activity", "대기 중..."),
        "containers": {
            "ameva-llm-main": "RUNNING",
            "ameva-llm-god": "RUNNING",
            "ameva-llm-bot-1": "RUNNING",
            "ameva-llm-bot-2": "RUNNING",
            "ameva-llm-bot-3": "RUNNING"
        }
    }

class SetupStartReq(BaseModel):
    inference_mode: str = "sequential"
    hardware_mode: str = "cpu"
    model_main: str = ""
    model_god: str = ""

@router.post("/api/control/setup_and_start")
async def setup_and_start(req: SetupStartReq):
    """
    설정을 초기화하고 브라우징 시뮬레이션을 시작합니다.
    """
    if state_manager.state != SystemState.IDLE:
        return {"error": "System is busy."}
    
    state_manager.set_state(SystemState.RUNNING)
    state_manager.current_activity = "시뮬레이션 초기화 중..."
    
    # 백그라운드 태스크 실행 (runner.py)
    from app.services.runner import run_session
    asyncio.create_task(run_session())
    return {"message": "Simulation started successfully"}

class NewSessionReq(BaseModel):
    inference_mode: str = "sequential"

@router.post("/api/control/new")
async def control_new(req: NewSessionReq = None):
    if state_manager.state != SystemState.IDLE:
        return {"error": "System is busy."}
    
    state_manager.set_state(SystemState.RUNNING)
    from app.services.runner import run_session
    asyncio.create_task(run_session())
    return {"message": "New browsing session started"}

@router.post("/api/control/pause")
async def control_pause():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No running session found."}
    state_manager.set_state(SystemState.PAUSING)
    return {"message": "Pausing session..."}

@router.post("/api/control/resume")
async def control_resume():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No active session found."}
    state_manager.set_state(SystemState.RUNNING)
    return {"message": "Session resumed"}

@router.post("/api/control/stop")
async def control_stop():
    if state_manager.state == SystemState.IDLE:
        return {"error": "No running session found."}
    state_manager.set_state(SystemState.STOPPING)
    return {"message": "Stopping session..."}

@router.post("/api/control/restart/{post_id}")
async def control_restart(post_id: int, db: DbSession = Depends(get_db)):
    if state_manager.state != SystemState.IDLE:
        return {"error": "System is busy."}
    
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        return {"error": f"Post #{post_id} not found."}
        
    session_id = post.session_id
    state_manager.set_state(SystemState.RUNNING)
    from app.services.runner import restart_session
    asyncio.create_task(restart_session(session_id))
    return {"message": f"Restarting post {post_id} (Session {session_id})"}
