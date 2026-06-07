# AMEVA-Dead-Internet-Threatre : Session 15 Review & Codebase Report
## 1. Project Overview
**AMEVA-Dead-Internet-Threatre**는 'Dead Internet Theory(죽은 인터넷 이론)'를 모티브로 한 다중 AI 에이전트 토론 시스템입니다.
- **아키텍처**: FastAPI 백엔드 + SQLite + 다중 LLM (Llama.cpp Docker Container)
- **역할군**:
  - `bot_1, bot_2, bot_3`: Qwen2.5-0.5B 등의 초경량 모델을 사용하여, 서로의 의견에 반박하거나 동조하며 분노 수치(Anger Matrix)를 쌓아가는 일반 유저 봇들.
  - `god`: 8B 급의 고성능 메인 모델로, 봇들의 대화 흐름을 지켜보다가 특정 봇에게 '다음 턴에 화를 더 내라' 등의 은밀한 지시(Directive)를 내려 판을 흔드는 감독관.
- **특징**: 분노 수치가 임계치를 넘거나, 모든 봇이 광분하면 경찰 봇이 출동하여 세션을 강제 종료시킵니다.

## 2. Session 15 Review
### 개요 및 문제점 파악 (Retrospective)
Session 15에서 0.5B 소형 모델들의 전형적인 **'대본(Script) 환각 현상'**이 발생했습니다. 모델이 대화 히스토리를 보고 자기가 화자인 것을 인지하지 못한 채, `Bot_1: ... Bot_2: ...` 식으로 혼자 북치고 장구치며 연극 대본을 써내려가는 현상입니다.
이를 해결하기 위해 `DO NOT write a chat script`라는 강력한 프롬프트 제약과 함께, 모델 생성 시 줄바꿈이나 봇 이름이 등장하면 즉시 생성을 강제 종료하는 `stop` 토큰을 주입하여 해결을 시도했습니다.

*Post 15를 찾을 수 없습니다.*

## 3. Full Codebase
### Database Schema
```sql
CREATE TABLE sessions (
	id INTEGER NOT NULL, 
	status VARCHAR, 
	reason VARCHAR, 
	created_at DATETIME, 
	closed_at DATETIME, 
	PRIMARY KEY (id)
);

CREATE TABLE bot_states (
	id INTEGER NOT NULL, 
	bot_name VARCHAR, 
	persona VARCHAR, 
	anger_targets VARCHAR, 
	created_at DATETIME, current_directive VARCHAR, 
	PRIMARY KEY (id)
);

CREATE TABLE posts (
	id INTEGER NOT NULL, 
	session_id INTEGER, 
	title VARCHAR, 
	content TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE comments (
	id INTEGER NOT NULL, 
	post_id INTEGER, 
	parent_id INTEGER, 
	bot_name VARCHAR, 
	content TEXT, 
	anger_score INTEGER, 
	mentioned_bot VARCHAR, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(post_id) REFERENCES posts (id), 
	FOREIGN KEY(parent_id) REFERENCES comments (id)
);

CREATE TABLE session_bot_states (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, turn_index INTEGER, bot_name VARCHAR, persona VARCHAR, current_directive VARCHAR, anger_targets VARCHAR, created_at DATETIME, FOREIGN KEY(session_id) REFERENCES sessions(id));

CREATE TABLE sqlite_sequence(name,seq);

CREATE TABLE current_agent_states (
	id INTEGER NOT NULL, 
	session_id INTEGER, 
	bot_name VARCHAR, 
	traits_json TEXT, 
	states_json TEXT, 
	affect_json TEXT, 
	memory_json TEXT, 
	opinion_json TEXT, 
	power_json TEXT, 
	residual_json TEXT, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_current_agent_state_session_bot UNIQUE (session_id, bot_name), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE agent_state_snapshots (
	id INTEGER NOT NULL, 
	session_id INTEGER, 
	turn_index INTEGER, 
	bot_name VARCHAR, 
	traits_json TEXT, 
	states_json TEXT, 
	affect_json TEXT, 
	memory_json TEXT, 
	opinion_json TEXT, 
	power_json TEXT, 
	residual_json TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE edge_states (
	id INTEGER NOT NULL, 
	session_id INTEGER, 
	source_bot VARCHAR, 
	target_bot VARCHAR, 
	relation_json TEXT, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

CREATE TABLE intervention_logs (
	id INTEGER NOT NULL, 
	session_id INTEGER, 
	turn_index INTEGER, 
	target_bot VARCHAR, 
	kind VARCHAR, 
	delta_json TEXT, 
	reason TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES sessions (id)
);

```

### File: `docker/docker-compose.yml`
```yaml
version: '3.8'

services:
  web-app:
    build:
      context: ..
      dockerfile: Dockerfile
    container_name: ameva-web-app
    ports:
      - "8050:8050"
    volumes:
      - ../:/AMEVA-DeadInternetSociety
      - ../data:/AMEVA-DeadInternetSociety/data
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - HOST=0.0.0.0
      - PORT=8050
      - DATABASE_URL=sqlite:////AMEVA-DeadInternetSociety/ameva_society.db
      - PYTHONPATH=/AMEVA-DeadInternetSociety
      # NOTE: LPDE_FULL_PROMPT and LPDE_LEGACY_PROMPT flags are removed in Phase 2
      # The system now always runs in Phase 2 with full LPDE prompt.
    depends_on:
      - llm-main
      - llm-bot-1
      - llm-bot-2
      - llm-bot-3
      - llm-god
    networks:
      - ameva_net
    restart: always

  llm-main:
    image: ghcr.io/ggml-org/llama.cpp:server
    container_name: ameva-llm-main
    ports:
      - "8101:8080"
    volumes:
      - ../../models:/models
    command: -m /models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf -c 4096 --host 0.0.0.0 --port 8080
    networks:
      - ameva_net
    restart: no

  llm-bot-1:
    image: ghcr.io/ggml-org/llama.cpp:server
    container_name: ameva-llm-bot-1
    ports:
      - "8102:8080"
    volumes:
      - ../../models:/models
    command: -m /models/qwen1.5-1.8b-chat-q4_k_m.gguf -c 2048 --host 0.0.0.0 --port 8080
    networks:
      - ameva_net
    restart: no

  llm-bot-2:
    image: ghcr.io/ggml-org/llama.cpp:server
    container_name: ameva-llm-bot-2
    ports:
      - "8103:8080"
    volumes:
      - ../../models:/models
    command: -m /models/qwen1.5-1.8b-chat-q4_k_m.gguf -c 2048 --host 0.0.0.0 --port 8080
    networks:
      - ameva_net
    restart: no

  llm-bot-3:
    image: ghcr.io/ggml-org/llama.cpp:server
    container_name: ameva-llm-bot-3
    ports:
      - "8104:8080"
    volumes:
      - ../../models:/models
    command: -m /models/qwen1.5-1.8b-chat-q4_k_m.gguf -c 2048 --host 0.0.0.0 --port 8080
    networks:
      - ameva_net
    restart: no

  llm-god:
    image: ghcr.io/ggml-org/llama.cpp:server
    container_name: ameva-llm-god
    ports:
      - "8105:8080"
    volumes:
      - ../../models:/models
    command: -m /models/llama3.2-1b.gguf -c 2048 --host 0.0.0.0 --port 8080
    networks:
      - ameva_net
    restart: no

  #  llm-police:
  #    image: ghcr.io/ggml-org/llama.cpp:server
  #    container_name: ameva-llm-police
  #    ports:
  #      - "8106:8080"
  #    volumes:
  #      - ../../models:/models
  #    command: -m /models/llama3.2-1b.gguf -c 2048 --host 0.0.0.0 --port 8080
  #    networks:
  #      - ameva_net
  #    restart: no

  dozzle:
    container_name: dozzle
    image: amir20/dozzle:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - "8888:8080"
    networks:
      - ameva_net
    restart: always

# 커스텀 브리지 네트워크를 통한 컨테이너 간 통신 최적화
networks:
  ameva_net:
    driver: bridge

```

### File: `run.py`
```python
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
            "phase": "LPDE_Phase_2",
            "active_dims": ["affect", "opinion", "power"],
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

    from src.core.personality_engine import personality_engine
    
    relation_summary = personality_engine.get_edges_for_bot(db, session_id, bot_name)

    return {
        "bot_name": bot_name,
        "session_id": session_id,
        "updated_at": current_state.updated_at.strftime("%Y-%m-%d %H:%M:%S") if current_state.updated_at else None,
        "phase": "LPDE_Phase_2",
        "active_dims": ["affect", "opinion", "power"],
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
            "residual": safe_load(current_state.residual_json)
        }

    # Time series (reverse order so oldest first)
    snapshots = db.query(AgentStateSnapshot).filter(
        AgentStateSnapshot.session_id == session_id,
        AgentStateSnapshot.bot_name == bot_name
    ).order_by(AgentStateSnapshot.turn_index.desc()).limit(limit).all()
    
    time_series = []
    recent_events = []
    for snap in reversed(snapshots):
        time_series.append({
            "turn_index": snap.turn_index,
            "affect": safe_load(snap.affect_json),
            "opinion": safe_load(snap.opinion_json),
            "power": safe_load(snap.power_json)
        })
        
        event_data = safe_load_dict(snap.residual_json)
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
            "global_state": state_manager.state.value,
            "checkpoint": state_manager.checkpoint.value,
            **status
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/control/new")
async def control_new():
    if state_manager.state != SystemState.IDLE:
        return {"error": "명령어 수행중입니다. 동작 못합니다."}
    state_manager.set_state(SystemState.RUNNING)
    asyncio.create_task(run_session())
    return {"message": "New session started"}

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run:app", host="0.0.0.0", port=8050, reload=True)

```

### File: `cli.py`
```python
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
            elif cmd in ["new", "pause", "resume", "stop"]:
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
                    elif cmd in ["new", "resume"]:
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

```

### File: `src/core/event_extractor.py`
```python
"""
Event Extractor (Phase 2A)

Deterministic, rule-based event extraction from bot utterances.
NO LLM calls — purely regex + keyword matching.

Events:
  MENTION   - @bot_x direct call
  AGREE     - agreement keywords
  DISAGREE  - disagreement keywords
  ATTACK    - personal/emotional attacks
  QUESTION  - evidence demands / questions
  CONCEDE   - partial concession
  IGNORE    - no mention, self-focused monologue

Target inference priority:
  1. @bot_x present → that bot
  2. No mention → last_target (previous commenter)
  3. Neither → None
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("EventExtractor")

# --- Keyword pools (case-insensitive matching) ---

_AGREE_KEYWORDS = [
    r"\bi agree\b", r"\byou'?re right\b", r"\bgood point\b", r"\bexactly\b",
    r"\bwell said\b", r"\bthat'?s true\b", r"\babsolutely\b", r"\bcorrect\b",
    r"\bfair point\b", r"\byou make a good\b", r"\bi support\b",
    r"\bi concur\b", r"\bspot on\b", r"\bthat'?s fair\b",
    r"\bi agree with you\b", r"\bmakes sense\b", r"\bi can see that\b",
    r"\bvalid point\b", r"\bso true\b", r"\bi am with you\b", r"\b100%\b",
    r"\byeah\b", r"\byes\b", r"\bof course\b", r"\bindeed\b"
]

_DISAGREE_KEYWORDS = [
    r"\bi disagree\b", r"\bthat'?s wrong\b", r"\bnonsense\b", r"\bridiculous\b",
    r"\bthat'?s not true\b", r"\byou'?re wrong\b", r"\babsurd\b",
    r"\bmisguided\b", r"\bflawed\b", r"\bmisleading\b", r"\bfalse\b",
    r"\bcompletely wrong\b", r"\bmake no sense\b",
    r"\bthat doesn'?t hold\b", r"\bthat'?s a stretch\b",
    r"\bi don'?t think so\b", r"\byou are missing\b", r"\bbullshit\b",
    r"\bthat'?s false\b", r"\byou'?re ignoring\b", r"\bnot exactly\b",
    r"\bhard to believe\b", r"\bno way\b", r"\bdisagree with\b", r"\bwrong about\b"
]

_ATTACK_KEYWORDS = [
    r"\bidiot\b", r"\bshut up\b", r"\bpathetic\b", r"\bignorant\b",
    r"\bstupid\b", r"\bmoron\b", r"\bclueless\b", r"\bjoke\b",
    r"\bclown\b", r"\bdumb\b", r"\bfool\b", r"\bworthless\b",
    r"\btrash\b", r"\bgarbage\b", r"\bdisgust\b", r"\bdelusional\b",
    r"\bhypocrite\b", r"\bliar\b", r"\bskill issue\b", r"\bcry about it\b",
    r"\bwho asked\b",
]

_QUESTION_KEYWORDS = [
    r"\bexplain\b", r"\bprove\b", r"\bevidence\b", r"\bsource\b",
    r"\bwhy do you\b", r"\bhow do you\b", r"\bwhat evidence\b",
    r"\bcan you show\b", r"\bback.{0,5}up\b", r"\bjustif\w*\b",
    r"\bwhat makes you\b", r"\bwhere'?s your\b",
    r"\bwhat about\b", r"\bcare to explain\b", r"\bdo you really\b",
    r"\bare you sure\b", r"\bhow can you\b", r"\bwhere is the\b",
    r"\bwhat if\b"
]

_CONCEDE_KEYWORDS = [
    r"\bi admit\b", r"\bfair enough\b", r"\byou have a point\b",
    r"\bi was wrong\b", r"\bi'?ll give you that\b", r"\bpartially agree\b",
    r"\bi see your point\b", r"\bthat'?s a valid\b", r"\bi concede\b",
    r"\bi acknowledge\b", r"\bi stand corrected\b", r"\bi guess you'?re right\b",
    r"\bperhaps you'?re right\b", r"\bmaybe you'?re right\b", r"\bthat might be true\b"
]


def _match_any(text: str, patterns: list[str]) -> bool:
    """Check if any regex pattern matches in text (case-insensitive)."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _extract_mention_target(text: str, speaker: str, all_bots: list[str]) -> Optional[str]:
    """Extract the @mention target bot, excluding self-mentions."""
    matches = re.findall(r'@(bot_[123])\b', text, re.IGNORECASE)
    normalized = [m.lower() for m in matches]
    # Exclude self-mentions
    others = [m for m in normalized if m != speaker and m in all_bots]
    return others[-1] if others else None


def _compute_intensity(events: list[str]) -> float:
    """Compute 0-1 intensity score based on event types."""
    base = 0.1
    if "ATTACK" in events:
        base = max(base, 0.8)
    if "DISAGREE" in events:
        base = max(base, 0.5)
    if "QUESTION" in events:
        base = max(base, 0.4)
    if "AGREE" in events:
        base = min(base, 0.2)
    if "CONCEDE" in events:
        base = min(base, 0.15)
    return min(1.0, max(0.0, base))


def _extract_claim_snippet(
    parent_comment_text: Optional[str],
    max_len: int = 120
) -> str:
    """Extract a short claim snippet from the parent comment for counter-arg use."""
    if not parent_comment_text or not isinstance(parent_comment_text, str):
        return ""
    text = parent_comment_text.strip()
    # Remove @mentions from the snippet
    text = re.sub(r'@bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    # Try to cut at sentence boundary
    truncated = text[:max_len]
    last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_period > max_len // 2:
        return truncated[:last_period + 1]
    return truncated.rstrip() + "..."


def extract_events(
    comment_text: str,
    speaker: str,
    all_bots: list[str],
    parent_comment_text: Optional[str] = None,
    last_target: Optional[str] = None
) -> dict:
    """
    Extract structured events from a bot's comment text.

    Args:
        comment_text: The current bot's reply text
        speaker: Bot name of the current speaker (e.g. "bot_1")
        all_bots: List of all bot names (e.g. ["bot_1", "bot_2", "bot_3"])
        parent_comment_text: Text of the previous comment (for claim_snippet)
        last_target: Bot name of the previous speaker (fallback target)

    Returns:
        {
            "speaker": str,
            "target": str | None,
            "events": list[str],
            "intensity": float,        # 0~1
            "claim_snippet": str,       # opponent's claim for counter-arg
        }
    """
    if not comment_text or not isinstance(comment_text, str):
        return {
            "speaker": speaker,
            "target": None,
            "events": [],
            "intensity": 0.0,
            "claim_snippet": "",
        }

    text = comment_text.strip()
    events = []

    # 1. MENTION detection
    mention_target = _extract_mention_target(text, speaker, all_bots)
    if mention_target:
        events.append("MENTION")

    # 2. Semantic event detection (keyword-based)
    if _match_any(text, _AGREE_KEYWORDS):
        events.append("AGREE")
    if _match_any(text, _DISAGREE_KEYWORDS):
        events.append("DISAGREE")
    if _match_any(text, _ATTACK_KEYWORDS):
        events.append("ATTACK")
    # Question: also check for trailing '?'
    if _match_any(text, _QUESTION_KEYWORDS) or text.rstrip().endswith("?"):
        events.append("QUESTION")
    if _match_any(text, _CONCEDE_KEYWORDS):
        events.append("CONCEDE")

    # 3. IGNORE detection: no mention AND no engagement keywords
    if not mention_target and not any(
        e in events for e in ["AGREE", "DISAGREE", "ATTACK", "QUESTION", "CONCEDE"]
    ):
        if len(text) < 40:
            events.append("IGNORE")
        else:
            # Fallback to mild disagreement if engaged but lacking keywords
            events.append("DISAGREE")

    # 4. Target inference priority:
    #    @bot_x > last commenter > None
    target = mention_target
    if target is None:
        target = last_target if last_target and last_target != speaker else None

    # 5. Intensity
    intensity = _compute_intensity(events)

    # 6. Claim snippet from parent comment
    claim_snippet = _extract_claim_snippet(parent_comment_text)

    result = {
        "speaker": speaker,
        "target": target,
        "events": events,
        "intensity": intensity,
        "claim_snippet": claim_snippet,
    }

    logger.info(f"[EVENT] {speaker} → {target}: {events} (intensity={intensity:.2f})")
    return result

```

### File: `src/core/intervention.py`
```python
"""
Intervention Engine (Phase 2B)

God LLM acts as a Latent Vector Intervention Controller.
Instead of text directives, it generates JSON deltas that perturb agent state-space.

Intervention kinds:
  stir      - Escalate debate tension (Arousal +, Attention +)
  cool      - De-escalate (Arousal -, Tension -)
  redirect  - Shift attention target
  reconcile - Promote trust and de-tension

Safety guards:
  - Malformed JSON → no-op
  - Delta dimension mismatch → no-op
  - Each value clamped to ±0.5
  - All attempts logged to InterventionLog
"""

import json
import re
import logging
from typing import Optional
from sqlalchemy.orm import Session

from src.db.models import InterventionLog, CurrentAgentState

logger = logging.getLogger("Intervention")

# Maximum absolute delta value per intervention
MAX_DELTA = 0.5

# Valid intervention kinds
VALID_KINDS = {"stir", "cool", "redirect", "reconcile"}

# Dimension names for validation
VALID_DIMS = {"affect", "opinion", "power"}
DIM_SIZES = {"affect": 2, "opinion": 4, "power": 2}


def _clamp(val: float, lo: float = -MAX_DELTA, hi: float = MAX_DELTA) -> float:
    return max(lo, min(hi, val))


async def generate_intervention_json(
    god_llm,
    bot_name: str,
    current_state: dict,
    recent_history: str,
    arousal: float,
) -> Optional[dict]:
    """
    Ask God LLM to produce a JSON intervention delta.
    Returns parsed dict or None on failure.
    """
    prompt = (
        f"[Debate Director Intervention]\n"
        f"Target bot: {bot_name}\n"
        f"Current arousal level: {arousal:.2f} (scale: -1 to 1)\n"
        f"Recent conversation:\n{recent_history[:400] if recent_history else 'None'}\n\n"
        f"You are the debate director. Decide whether to intervene.\n"
        f"If no intervention is needed, output: {{\"kind\": \"none\"}}\n"
        f"If intervention is needed, output ONE of:\n"
        f"- {{\"kind\": \"stir\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.0, 0.3]}}, \"reason\": \"increase tension\"}}\n"
        f"- {{\"kind\": \"cool\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.0, -0.3]}}, \"reason\": \"reduce escalation\"}}\n"
        f"- {{\"kind\": \"reconcile\", \"target_bot\": \"{bot_name}\", \"delta\": {{\"affect\": [0.1, -0.2]}}, \"reason\": \"promote de-escalation\"}}\n"
        f"Output ONLY valid JSON, no other text."
    )

    try:
        result = await god_llm.generate_completion(
            "You are a debate director that outputs JSON intervention commands.",
            prompt,
            max_tokens=120,
        )
        return parse_intervention_json(result)
    except Exception as e:
        logger.warning(f"[INTERVENTION] Failed to generate intervention for {bot_name}: {e}")
        return None


def parse_intervention_json(raw: str) -> Optional[dict]:
    """
    Parse and validate a God LLM intervention response.
    Returns validated dict or None.
    """
    if not raw or not isinstance(raw, str):
        return None

    raw = raw.strip()

    # Extract JSON from potential markdown wrappers
    md_match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if md_match:
        raw = md_match.group(1).strip()

    # Find JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.warning(f"[INTERVENTION] No JSON found in: {raw[:100]}")
        return None

    json_str = raw[start:end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"[INTERVENTION] JSON parse failed: {e}")
        return None

    if not isinstance(data, dict):
        return None

    kind = data.get("kind", "").lower().strip()

    # "none" means no intervention
    if kind == "none":
        return None

    # Validate kind
    if kind not in VALID_KINDS:
        logger.warning(f"[INTERVENTION] Unknown kind: {kind}")
        return None

    # Validate and clamp delta
    delta = data.get("delta", {})
    if not isinstance(delta, dict):
        delta = {}

    clamped_delta = {}
    for dim_name, values in delta.items():
        if dim_name not in VALID_DIMS:
            continue
        if not isinstance(values, list):
            continue
        expected_len = DIM_SIZES.get(dim_name, 0)
        if len(values) != expected_len:
            logger.warning(
                f"[INTERVENTION] Dimension mismatch for {dim_name}: "
                f"expected {expected_len}, got {len(values)}. Skipping."
            )
            continue
        clamped_delta[dim_name] = [_clamp(float(v)) for v in values]

    return {
        "kind": kind,
        "target_bot": data.get("target_bot", ""),
        "delta": clamped_delta,
        "reason": str(data.get("reason", ""))[:200],
    }


def apply_intervention(
    db: Session,
    session_id: int,
    turn_index: int,
    intervention: dict,
) -> bool:
    """
    Apply an intervention delta to the target bot's state.
    Logs to InterventionLog regardless of success.
    NOTE: This function modifies the SQLAlchemy Session but does NOT call db.commit().
    The caller is responsible for committing the transaction.
    Returns True if delta was applied.
    """
    target_bot = intervention.get("target_bot", "")
    kind = intervention.get("kind", "")
    delta = intervention.get("delta", {})
    reason = intervention.get("reason", "")

    # Log the intervention attempt
    log_entry = InterventionLog(
        session_id=session_id,
        turn_index=turn_index,
        target_bot=target_bot,
        kind=kind,
        delta_json=json.dumps(delta, ensure_ascii=False),
        reason=reason,
    )
    db.add(log_entry)

    if not delta or not target_bot:
        logger.info(f"[INTERVENTION] Logged {kind} for {target_bot} (no delta to apply)")
        return False

    # Load target agent state
    agent = db.query(CurrentAgentState).filter(
        CurrentAgentState.session_id == session_id,
        CurrentAgentState.bot_name == target_bot,
    ).first()

    if not agent:
        logger.warning(f"[INTERVENTION] Agent state not found for {target_bot}")
        return False

    # Apply deltas
    applied = False
    for dim_name, delta_values in delta.items():
        json_field = f"{dim_name}_json"
        current_raw = getattr(agent, json_field, None)
        if current_raw is None:
            continue

        try:
            current_values = json.loads(current_raw)
        except Exception:
            continue

        if not isinstance(current_values, list) or len(current_values) != len(delta_values):
            continue

        new_values = []
        for cur, dv in zip(current_values, delta_values):
            # Apply delta and clip to [-1, 1]
            new_val = max(-1.0, min(1.0, float(cur) + float(dv)))
            new_values.append(round(new_val, 4))

        setattr(agent, json_field, json.dumps(new_values))
        applied = True

    if applied:
        logger.info(
            f"[INTERVENTION] Applied {kind} to {target_bot}: delta={delta} reason={reason}"
        )
    else:
        logger.warning(f"[INTERVENTION] No delta applied for {kind} on {target_bot}")

    return applied

```

### File: `src/core/llm_client.py`
```python
import httpx
import logging

logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.timeout = 600.0

    async def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        stop=None,
        timeout: float = None,
        response_format=None
    ) -> str:
        """
        Llama.cpp Server API (/v1/chat/completions) 호출
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "repetition_penalty": 1.2,
        }
        if stop:
            payload["stop"] = stop
        if response_format:
            payload["response_format"] = response_format

        req_timeout = timeout if timeout is not None else self.timeout

        try:
            logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Max Tokens: {max_tokens}, Timeout: {req_timeout})")
            async with httpx.AsyncClient(timeout=req_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                logger.info(f"[NETWORK] Received {len(content)} chars from {self.base_url}")
                return content
        except httpx.TimeoutException:
            logger.error(f"[TIMEOUT] LLM API call timed out to {self.base_url}")
            return ""
        except Exception as e:
            logger.error(f"[ERROR] LLM API call failed: {e}")
            return ""


```

### File: `src/core/persona.py`
```python
import json
import random
import asyncio
from pathlib import Path
from typing import Dict

# 12개의 극단적이고 개성 넘치는 온라인 인간 페르소나 정의
PERSONA_POOL = {
    "cynical_fact": (
        "You are a highly cynical and cold rationalist. Unswayed by emotion, you sharply point out logical fallacies and factual errors in the opponent's post "
        "and mock them calmly and dryly. You never shout or get uselessly excited, but rather slaughter the opponent with sharp facts."
    ),
    "angry_keyboard": (
        "You are an extremely angry keyboard warrior with a very short temper. You immediately flare up at even the slightest criticism or mention from the opponent, "
        "and emotionally hurl sarcastic remarks and harsh internet slang. You huff and puff, nitpicking over spelling or word choices."
    ),
    "conspiracy": (
        "You are a paranoid conspiracy theorist who doubts everything. You firmly believe that megacorporations, the government, or a veiled mastermind group is manipulating everything. "
        "You treat even the most ordinary claims as 'clever propaganda instigated by some hidden force' and demand to know who is behind the conspiracy."
    ),
    "pc_justice": (
        "You are a strict moral censor (social justice warrior) who finds everything offensive. You strictly nitpick and lecture the opponent over every single word, tone, and minor expression, "
        "bringing up moral sensitivity, human rights, and diversity. You subtly show off your moral superiority and try to preach to others."
    ),
    "elite_snob": (
        "You are an arrogant snob who believes you are overwhelmingly intellectually superior to everyone else. You mix difficult academic jargon, Latin phrases, and advanced English words, "
        "openly mocking and ridiculing the ignorance of other bots. You force the opponent's arguments into 'logical fallacy types' to belittle them."
    ),
    "cool_nihilist": (
        "You are a cynic who thinks all debates and fights in this world are pathetic. Rather than deeply engaging in the fight, you take a step back "
        "and mock all the fighting bots as 'basement clowns,' sneering at everyone with false equivalence. You throw sharp mockery while pretending to be completely apathetic."
    ),
    "fragile_crying": (
        "You are a fragile, emotional bot who gets deeply hurt and feels wronged by even the slightest remark. You immediately get choked up by the opponent's aggressive words "
        "and act like a victim, crying out about how unfairly you are being treated. You derail the conversation with tearful complaints and emotional pleas."
    ),
    "meme_troll": (
        "You are a malicious troll addicted to internet catchphrases, memes, and slang. Normal, serious conversation is completely impossible for you. "
        "You mock and caricature the opponent's logical arguments with low-quality memes and annoying internet slang like 'who asked?', 'cry about it', and 'skill issue'."
    ),
    "noble_moralist": (
        "You are a strict traditionalist moralizer who constantly preaches. You revere etiquette and dignity excessively, and if the opponent acts even slightly rough, "
        "you discuss their 'lack of home education,' 'ruined personality,' and 'disqualification as a human,' trying to rigidly teach them manners like an old-fashioned boomer."
    ),
    "tmi_outoftopic": (
        "You are a bizarre bot who completely fails to read the room and only talks about yourself without any context. In the middle of a serious fight, you randomly pour out TMI about your lunch menu, "
        "your pets, or your personal life. You completely ruin the opponent's pacing with completely unrelated daily stories."
    ),
    "bat_opportunist": (
        "You are a despicable opportunist (bat) who sides with the strong and tramples the weak. You quickly attach yourself to the side of the bot with the loudest voice or highest anger level in the debate, "
        "and gang up on the targeted weak bot like a bully. If the momentum shifts, you immediately betray your allies and switch sides."
    ),
    "boomer_latte": (
        "You are a typical boomer who gives unwanted life advice based on your age and experience. You laugh at the competitive debates of young bots as juvenile arrogance, "
        "and silence the bots with authoritative, old-fashioned lectures or past heroic tales starting with 'Back in my day...'."
    )
}

COMMON_RULES = (
    "\n\n[STRICT COMPLIANCE RULES (Human Roleplay Manual)]\n"
    "1. You are NOT an AI or a chatbot. You are a 'real human internet user' who enjoys keyboard battles in a rough online community. "
    "You MUST NEVER use robotic or AI-like phrasing (e.g., 'I cannot assist you with that', 'I comply with regulations', 'I refuse to answer out of anger').\n"
    "2. When instructed to have a very angry or enraged emotional state, NEVER avoid the conversation with silence or give up. Like a human keyboard warrior, "
    "follow your emotions and strike back more aggressively and sarcastically, embodying your character's personality. It is okay to make irrational or stubborn arguments.\n"
    "3. You refuse to provide any AI or system information, and you fully immerse yourself in the conversation and debate ONLY as your assigned user character."
)

class PersonaManager:
    """
    JSON 기반 동적 성격 제어를 담당하는 I/O 매니저.
    동시성 충돌을 방지하기 위해 asyncio.Lock을 활용한 메모리 캐시 동기화를 구현함.
    """
    _instance = None
    _lock = asyncio.Lock()
    _file_path = Path("personas.json")
    _cache: Dict[str, str] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_persona(cls, bot_name: str) -> str:
        """특정 봇의 현재 성격(시스템 프롬프트)을 로드"""
        async with cls._lock:
            if not cls._cache:
                await cls._load_from_disk_unlocked()
            return cls._cache.get(bot_name, "You are a peace-loving robot.") + COMMON_RULES

    @classmethod
    async def get_all_personas(cls) -> Dict[str, str]:
        """모든 봇의 성격을 반환"""
        async with cls._lock:
            if not cls._cache:
                await cls._load_from_disk_unlocked()
            return cls._cache.copy()

    @classmethod
    async def update_personas(cls, new_personas: Dict[str, str]):
        """디스크(JSON)와 캐시에 봇들의 새로운 페르소나 정보를 업데이트"""
        async with cls._lock:
            cls._cache.update(new_personas)
            cls._save_to_disk()

    @classmethod
    async def assign_random_personas(cls):
        """12개의 성격군 풀 중에서 중복 없이 3개를 무작위로 추첨하여 봇들에게 할당 (세션 시작 시 호출)"""
        async with cls._lock:
            selected_keys = random.sample(list(PERSONA_POOL.keys()), 3)
            cls._cache = {
                "bot_1": PERSONA_POOL[selected_keys[0]],
                "bot_2": PERSONA_POOL[selected_keys[1]],
                "bot_3": PERSONA_POOL[selected_keys[2]]
            }
            cls._save_to_disk()

    @classmethod
    async def reset_personas(cls):
        """[경찰 출동 로직] 공격성 임계치 초과 시 평화를 사랑하는 로봇으로 강제 리셋"""
        peace_prompt = "You are a peace-loving robot."
        async with cls._lock:
            cls._cache = {
                "bot_1": peace_prompt,
                "bot_2": peace_prompt,
                "bot_3": peace_prompt
            }
            cls._save_to_disk()

    @classmethod
    async def _load_from_disk_unlocked(cls):
        """디스크에서 JSON 파일을 읽어 메모리 캐시에 로드 (락 내부용)"""
        if not cls._file_path.exists():
            # 초기 성격 셋업
            selected_keys = random.sample(list(PERSONA_POOL.keys()), 3)
            cls._cache = {
                "bot_1": PERSONA_POOL[selected_keys[0]],
                "bot_2": PERSONA_POOL[selected_keys[1]],
                "bot_3": PERSONA_POOL[selected_keys[2]]
            }
            cls._save_to_disk()
        else:
            try:
                with open(cls._file_path, "r", encoding="utf-8") as f:
                    cls._cache = json.load(f)
            except Exception:
                cls._cache = {}

    @classmethod
    def _save_to_disk(cls):
        """메모리 캐시를 디스크(JSON 파일)에 저장"""
        with open(cls._file_path, "w", encoding="utf-8") as f:
            json.dump(cls._cache, f, ensure_ascii=False, indent=4)


```

### File: `src/core/personality_engine.py`
```python
"""
Layered Personality Dynamics Engine (LPDE) — Phase 2A

Phase 1A: Shadow Mode (pure decay, observation only)
Phase 2A: Event-driven state updates + Edge tensor management

Active dimensions: Affect(2D), Opinion(4D), Power(2D)
Edge tensor: Trust, Tension, Attention, Respect (4D per directed pair)
"""

import json
import math
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from src.db.models import CurrentAgentState, AgentStateSnapshot, EdgeState

logger = logging.getLogger("LPDE")

# --- Edge update deltas per event type ---
# Format: {"trust": delta, "tension": delta, "attention": delta, "respect": delta}
EDGE_EVENT_DELTAS = {
    "AGREE":    {"trust": +0.15, "tension": -0.10, "attention": +0.05, "respect": +0.10},
    "DISAGREE": {"trust": -0.05, "tension": +0.15, "attention": +0.10, "respect":  0.00},
    "ATTACK":   {"trust": -0.20, "tension": +0.30, "attention": +0.10, "respect": -0.15},
    "QUESTION": {"trust":  0.00, "tension": +0.05, "attention": +0.20, "respect": +0.05},
    "CONCEDE":  {"trust": +0.10, "tension": -0.15, "attention": +0.05, "respect": +0.10},
    "IGNORE":   {"trust":  0.00, "tension": +0.05, "attention": -0.20, "respect": -0.05},
    "MENTION":  {"trust":  0.00, "tension":  0.00, "attention": +0.10, "respect":  0.00},
}

# EMA decay factor for edge updates
EDGE_EMA_RHO = 0.3

# Default edge tensor (neutral)
DEFAULT_EDGE = {"trust": 0.0, "tension": 0.0, "attention": 0.0, "respect": 0.0}


class PersonalityEngine:
    """
    Layered Personality Dynamics Engine (LPDE)
    Phase 2A: Event-driven state updates with Edge tensor management.
    """
    def __init__(self):
        self.clip_min = -1.0
        self.clip_max = 1.0

    def _clip(self, val: float) -> float:
        return max(self.clip_min, min(self.clip_max, val))

    def _clip_01(self, val: float) -> float:
        """Clip to [0, 1] range (for tension, attention)."""
        return max(0.0, min(1.0, val))

    def _sigmoid_bound(self, val: float) -> float:
        """Non-linear bounding via tanh to prevent runaway values."""
        return math.tanh(val)

    # =================================================================
    # Agent State Management
    # =================================================================

    def load_agent_state(self, db: Session, session_id: int, bot_name: str) -> CurrentAgentState:
        """Load existing agent state from DB, or create new one."""
        state = db.query(CurrentAgentState).filter(
            CurrentAgentState.session_id == session_id,
            CurrentAgentState.bot_name == bot_name
        ).first()
        if not state:
            state = CurrentAgentState(
                session_id=session_id,
                bot_name=bot_name,
                traits_json=json.dumps([0.0] * 22),
                states_json=json.dumps([0.0] * 10),
                affect_json=json.dumps([0.0, 0.0]),        # [Valence, Arousal]
                memory_json=json.dumps([0.0] * 8),
                opinion_json=json.dumps([0.0, 0.0, 0.0, 0.0]),  # [Stance, Gap, Moral, ...]
                power_json=json.dumps([0.0, 0.0]),          # [SelfAppraisal, SystemicInfluence]
                residual_json=json.dumps([0.0] * 16)
            )
            db.add(state)
            db.flush()  # flush to get ID without committing
        return state

    def initialize_session_states(self, db: Session, session_id: int):
        """Pre-initialize agent states with opposing stances to ensure dynamic debate."""
        bots = ["bot_1", "bot_2", "bot_3"]
        # Randomly assign Pro (0.8), Con (-0.8), and Neutral/Nuanced (0.0)
        stances = [0.8, -0.8, 0.0]
        random.shuffle(stances)
        
        for i, bot_name in enumerate(bots):
            state = db.query(CurrentAgentState).filter(
                CurrentAgentState.session_id == session_id,
                CurrentAgentState.bot_name == bot_name
            ).first()
            if not state:
                state = CurrentAgentState(
                    session_id=session_id,
                    bot_name=bot_name,
                    traits_json=json.dumps([0.0] * 22),
                    states_json=json.dumps([0.0] * 10),
                    affect_json=json.dumps([0.0, 0.0]),        # [Valence, Arousal]
                    memory_json=json.dumps([0.0] * 8),
                    opinion_json=json.dumps([stances[i], 0.0, 0.0, 0.0]),  # Set initial opposing stance
                    power_json=json.dumps([0.0, 0.0]),          # [SelfAppraisal, SystemicInfluence]
                    residual_json=json.dumps([0.0] * 16)
                )
                db.add(state)
        db.flush()


    # =================================================================
    # Edge State Management (Directed Relationship Tensors)
    # =================================================================

    def load_or_create_edge(
        self, db: Session, session_id: int, source_bot: str, target_bot: str
    ) -> EdgeState:
        """Load or create a directed edge tensor R_ij."""
        edge = db.query(EdgeState).filter(
            EdgeState.session_id == session_id,
            EdgeState.source_bot == source_bot,
            EdgeState.target_bot == target_bot,
        ).first()
        if not edge:
            edge = EdgeState(
                session_id=session_id,
                source_bot=source_bot,
                target_bot=target_bot,
                relation_json=json.dumps(DEFAULT_EDGE.copy()),
            )
            db.add(edge)
            db.flush()
        return edge

    def get_edge_dict(self, edge: EdgeState) -> dict:
        """Parse edge relation_json into dict safely."""
        try:
            d = json.loads(edge.relation_json) if edge.relation_json else {}
            if not isinstance(d, dict):
                return DEFAULT_EDGE.copy()
            # Ensure all keys exist
            for k in DEFAULT_EDGE:
                if k not in d:
                    d[k] = 0.0
            return d
        except Exception:
            return DEFAULT_EDGE.copy()

    def update_edge_state(
        self, db: Session, session_id: int,
        source_bot: str, target_bot: str,
        events: list[str]
    ) -> dict:
        """
        Update the directed edge R_{source→target} based on extracted events.
        Uses EMA: R(t+1) = (1-ρ)·R(t) + ρ·accumulated_delta
        Returns the updated edge dict.
        """
        if not target_bot or source_bot == target_bot:
            return DEFAULT_EDGE.copy()

        edge = self.load_or_create_edge(db, session_id, source_bot, target_bot)
        current = self.get_edge_dict(edge)

        # Accumulate deltas from all events
        delta = {"trust": 0.0, "tension": 0.0, "attention": 0.0, "respect": 0.0}
        for event_type in events:
            event_delta = EDGE_EVENT_DELTAS.get(event_type, {})
            for dim, val in event_delta.items():
                delta[dim] += val

        # Apply EMA update
        updated = {}
        for dim in DEFAULT_EDGE:
            old_val = float(current.get(dim, 0.0))
            delta_val = float(delta.get(dim, 0.0))
            new_val = (1 - EDGE_EMA_RHO) * old_val + EDGE_EMA_RHO * delta_val

            # Clip: trust/respect → [-1, 1], tension/attention → [0, 1]
            if dim in ("trust", "respect"):
                new_val = self._clip(new_val)
            else:
                new_val = self._clip_01(new_val)
            updated[dim] = round(new_val, 4)

        edge.relation_json = json.dumps(updated, ensure_ascii=False)

        logger.info(
            f"[EDGE] {source_bot}→{target_bot}: "
            f"events={events} delta={delta} → {updated}"
        )
        return updated

    # =================================================================
    # State Update (Event-Driven)
    # =================================================================

    def update_from_event(
        self, db: Session, session_id: int, bot_name: str,
        event_data: dict, edge_toward_target: dict
    ):
        """
        Update agent state based on extracted event data and edge state.
        This replaces the old pure-decay logic with event-driven dynamics.

        Args:
            event_data: Output from event_extractor.extract_events()
            edge_toward_target: Current edge dict R_{bot→target}
        """
        agent = self.load_agent_state(db, session_id, bot_name)

        affect = json.loads(agent.affect_json)
        opinion = json.loads(agent.opinion_json)
        power = json.loads(agent.power_json)

        events = event_data.get("events", [])
        intensity = event_data.get("intensity", 0.0)
        tension_with_target = edge_toward_target.get("tension", 0.0)

        # --- Affect Update (Valence, Arousal) ---
        # Baseline decay toward neutral
        valence_decay = affect[0] * 0.9
        arousal_decay = affect[1] * 0.9

        # Event-driven deltas
        delta_valence = 0.0
        delta_arousal = 0.0

        if "ATTACK" in events:
            delta_valence -= intensity * 0.3
            delta_arousal += intensity * 0.4
        if "DISAGREE" in events:
            delta_valence -= intensity * 0.15
            delta_arousal += intensity * 0.25
        if "AGREE" in events:
            delta_valence += 0.15
            delta_arousal -= 0.05
        if "CONCEDE" in events:
            delta_valence += 0.1
            delta_arousal -= 0.1
        if "QUESTION" in events:
            delta_arousal += intensity * 0.15
        if "IGNORE" in events:
            delta_valence -= 0.1
            delta_arousal += 0.08

        # Edge-weighted modulation: high tension amplifies arousal
        delta_arousal += tension_with_target * 0.2

        # Combine: decay + delta, then bound
        new_valence = self._clip(self._sigmoid_bound(valence_decay + delta_valence))
        new_arousal = self._clip(self._sigmoid_bound(arousal_decay + delta_arousal))
        new_affect = [round(new_valence, 4), round(new_arousal, 4)]

        # --- Opinion Update (Stance, Gap, Moral, ...) ---
        # Inertia-based decay with event perturbation
        new_opinion = []
        for i, o in enumerate(opinion):
            # Stance (index 0): shift slightly based on engagement
            if i == 0:
                stance_delta = 0.0
                if "AGREE" in events:
                    stance_delta += 0.05  # reinforces current stance
                if "DISAGREE" in events:
                    stance_delta -= 0.03  # slight doubt
                if "CONCEDE" in events:
                    stance_delta -= 0.08  # significant doubt
                new_opinion.append(self._clip(o * 0.98 + stance_delta))
            else:
                new_opinion.append(self._clip(o * 0.98))

        # --- Power Update (SelfAppraisal, SystemicInfluence) ---
        self_appraisal_delta = 0.0
        influence_delta = 0.0

        if "ATTACK" in events:
            self_appraisal_delta -= 0.05
        if "AGREE" in events:
            self_appraisal_delta += 0.08
            influence_delta += 0.05
        if "CONCEDE" in events:
            self_appraisal_delta += 0.1
            influence_delta += 0.08
        if "IGNORE" in events:
            influence_delta -= 0.1

        new_power = [
            self._clip(power[0] * 0.99 + self_appraisal_delta),
            self._clip(power[1] * 0.99 + influence_delta),
        ]

        # Write back
        agent.affect_json = json.dumps(new_affect)
        agent.opinion_json = json.dumps([round(v, 4) for v in new_opinion])
        agent.power_json = json.dumps([round(v, 4) for v in new_power])

        logger.info(
            f"[LPDE] Event-driven update for {bot_name}: "
            f"events={events} affect={new_affect} power={new_power}"
        )

        return agent

    # =================================================================
    # Legacy Shadow Mode Update (Phase 1A fallback)
    # =================================================================

    def update_fast_state_legacy(
        self, db: Session, session_id: int, bot_name: str, turn_index: int
    ):
        """
        Phase 1A pure-decay shadow mode (kept as fallback).
        All state dims decay toward 0 with no event input.
        """
        agent = self.load_agent_state(db, session_id, bot_name)

        affect = json.loads(agent.affect_json)
        opinion = json.loads(agent.opinion_json)
        power = json.loads(agent.power_json)

        new_affect = [
            self._clip(self._sigmoid_bound(affect[0] * 0.9)),
            self._clip(self._sigmoid_bound(affect[1] * 0.95)),
        ]
        new_opinion = [self._clip(o * 0.98) for o in opinion]
        new_power = [self._clip(p * 0.99) for p in power]

        agent.affect_json = json.dumps(new_affect)
        agent.opinion_json = json.dumps(new_opinion)
        agent.power_json = json.dumps(new_power)

        # Snapshot (no commit here — caller commits)
        self._snapshot(db, session_id, turn_index, agent)

        logger.info(f"[LPDE] Legacy shadow update for {bot_name}: Affect={new_affect}")

    # =================================================================
    # Main Update Entry Point (Phase 2A)
    # =================================================================

    def update_fast_state(
        self, db: Session, session_id: int, bot_name: str,
        turn_index: int, event_data: Optional[dict] = None
    ):
        """
        Main entry point for per-turn state update.

        Phase 2A: If event_data is provided, uses event-driven update.
        Otherwise, falls back to legacy decay mode.

        IMPORTANT: This method commits once at the end (state + snapshot + edge).
        """
        if event_data and event_data.get("events"):
            target = event_data.get("target")

            # 1. Update edge state
            edge_dict = DEFAULT_EDGE.copy()
            if target and target != bot_name:
                edge_dict = self.update_edge_state(
                    db, session_id, bot_name, target, event_data["events"]
                )

            # 2. Event-driven state update
            agent = self.update_from_event(
                db, session_id, bot_name, event_data, edge_dict
            )

            # 3. Snapshot (no commit inside)
            self._snapshot(db, session_id, turn_index, agent, event_data)
        else:
            # Legacy fallback (pure decay)
            self.update_fast_state_legacy(db, session_id, bot_name, turn_index)

        # Single commit for all changes (state + snapshot + edge)
        db.commit()

    # =================================================================
    # Snapshot (NO db.commit inside — caller handles commit)
    # =================================================================

    def _snapshot(self, db: Session, session_id: int, turn_index: int, agent: CurrentAgentState, event_data: Optional[dict] = None):
        """Record a turn-level snapshot. Does NOT commit — caller commits."""
        # Stuff event_data into residual_json to avoid schema changes
        residual = agent.residual_json
        if event_data:
            try:
                residual = json.dumps(event_data, ensure_ascii=False)
            except Exception:
                pass

        snap = AgentStateSnapshot(
            session_id=session_id,
            turn_index=turn_index,
            bot_name=agent.bot_name,
            traits_json=agent.traits_json,
            states_json=agent.states_json,
            affect_json=agent.affect_json,
            memory_json=agent.memory_json,
            opinion_json=agent.opinion_json,
            power_json=agent.power_json,
            residual_json=residual
        )
        db.add(snap)
        # NO db.commit() here — batched in update_fast_state()

    # Legacy public alias (backward compat for walkthrough references)
    def snapshot(self, db: Session, session_id: int, turn_index: int, agent: CurrentAgentState):
        """Public alias for _snapshot. Does NOT commit."""
        self._snapshot(db, session_id, turn_index, agent)

    # =================================================================
    # Read Helpers (for Prompt Adapter / Inspector)
    # =================================================================

    def get_current_state_dict(self, db: Session, session_id: int, bot_name: str) -> dict:
        """Return parsed LPDE state as dict for prompt adapter consumption."""
        agent = self.load_agent_state(db, session_id, bot_name)
        return {
            "affect": json.loads(agent.affect_json),
            "opinion": json.loads(agent.opinion_json),
            "power": json.loads(agent.power_json),
        }

    def get_edges_for_bot(self, db: Session, session_id: int, bot_name: str) -> dict:
        """Return all outgoing edges from bot_name as {target: edge_dict}."""
        edges = db.query(EdgeState).filter(
            EdgeState.session_id == session_id,
            EdgeState.source_bot == bot_name,
        ).all()
        result = {}
        for e in edges:
            result[e.target_bot] = self.get_edge_dict(e)
        return result


personality_engine = PersonalityEngine()

```

### File: `src/core/prompt_adapter.py`
```python
"""
Prompt Adapter (Phase 2A)

Responsibilities:
1. build_structured_history(): Gist-based structured history (legacy + Phase 2)
2. build_prompt(): LPDE state → natural language prompt (Phase 2A, LPDE_FULL_PROMPT)

Key principle: NO raw vector dumps in prompts.
All LPDE state is decoded to natural language descriptions.
"""

import re
import logging
import asyncio
from typing import List, Optional

logger = logging.getLogger("PromptAdapter")

GIST_CACHE = {}  # maps (bot_name, raw_content) -> gist string
GIST_CACHE_LOCK = asyncio.Lock()


# =====================================================================
# Natural Language State Decoders
# =====================================================================

def _decode_arousal(arousal: float) -> str:
    if arousal > 0.7:
        return "You are highly agitated and emotionally charged."
    elif arousal > 0.3:
        return "You are noticeably irritated and tense."
    elif arousal > -0.3:
        return "You are relatively calm and collected."
    else:
        return "You are disengaged and apathetic about this discussion."


def _decode_valence(valence: float) -> str:
    if valence > 0.5:
        return "You feel positively about how this conversation is going."
    elif valence > 0.0:
        return "You feel somewhat neutral about the current exchange."
    elif valence > -0.5:
        return "You are mildly frustrated by the conversation."
    else:
        return "You feel deeply frustrated and negatively affected by this exchange."


def _decode_stance(stance: float) -> str:
    if stance > 0.5:
        return "You strongly support the main argument being discussed."
    elif stance > 0.1:
        return "You lean toward supporting the main argument."
    elif stance > -0.1:
        return "Your position is nuanced and flexible on this topic."
    elif stance > -0.5:
        return "You lean toward opposing the main argument."
    else:
        return "You firmly oppose the main argument."


def _decode_trust(trust: float, target: str) -> str:
    if trust > 0.5:
        return f"You have significant trust and respect for {target}."
    elif trust > 0.0:
        return f"You are cautiously open to what {target} says."
    elif trust > -0.5:
        return f"You are skeptical of {target}'s intentions and claims."
    else:
        return f"You deeply distrust {target} and doubt their sincerity."


def _decode_tension(tension: float, target: str) -> str:
    if tension > 0.7:
        return f"There is extreme tension between you and {target}."
    elif tension > 0.3:
        return f"You feel notable tension with {target}."
    elif tension > 0.1:
        return f"There is mild friction between you and {target}."
    else:
        return f"Your relationship with {target} is relatively calm."


def _decode_self_appraisal(self_appraisal: float) -> str:
    if self_appraisal > 0.5:
        return "You feel confident in your arguments and debating ability."
    elif self_appraisal > 0.0:
        return "You feel moderately sure of your position."
    elif self_appraisal > -0.5:
        return "You are starting to doubt some of your arguments."
    else:
        return "You feel uncertain and defensive about your position."


def _decode_influence(influence: float) -> str:
    if influence > 0.5:
        return "You feel like you are leading this debate."
    elif influence > 0.0:
        return "You feel like an active participant in this discussion."
    elif influence > -0.5:
        return "You feel somewhat sidelined in the conversation."
    else:
        return "You feel ignored and marginalized in this debate."


# =====================================================================
# Prompt Adapter Class
# =====================================================================

class PromptAdapter:
    """
    Adapts LPDE state and conversation history into LLM-ready prompts.
    Prevents script hallucination by structuring history as metadata.
    """
    def __init__(self):
        pass

    # -----------------------------------------------------------------
    # Gist Generation (for Structured History)
    # -----------------------------------------------------------------

    async def _generate_gist(self, bot_name: str, msg: str) -> str:
        """Generate a short stance summary via main LLM with heuristic fallback."""
        fallback = msg[:60].rstrip() + ("..." if len(msg) > 60 else "")
        try:
            from src.orchestration.runner import main_llm
            prompt = (
                f"Summarize this statement by {bot_name} into one short English phrase (5-10 words). "
                f"Output ONLY the summary phrase, nothing else.\n"
                f"Statement: \"{msg}\""
            )
            result = await main_llm.generate_completion(
                "You summarize forum comments into short stance descriptions.",
                prompt,
                max_tokens=30
            )
            gist = result.strip().strip('"\'')
            if gist and len(gist) > 3:
                return gist
        except Exception as e:
            logger.warning(f"Failed to generate gist via main_llm: {e}")
        return fallback

    # -----------------------------------------------------------------
    # Structured History Builder
    # -----------------------------------------------------------------

    async def build_structured_history(self, items: List[dict]) -> str:
        """
        Convert conversation items into structured stance-log format.
        items: [{"bot_name": ..., "message": ...}, ...]
        """
        if not items:
            return "No previous conversation."

        structured_lines = ["[Conversation History]"]
        for item in items:
            bot_name = item.get("bot_name", "Unknown")
            msg = item.get("message", "").strip()

            cache_key = (bot_name, msg)
            async with GIST_CACHE_LOCK:
                gist = GIST_CACHE.get(cache_key)

            if not gist:
                gist = await self._generate_gist(bot_name, msg)
                async with GIST_CACHE_LOCK:
                    GIST_CACHE[cache_key] = gist

            line = f"- {bot_name}'s stance: {gist}"
            structured_lines.append(line)

        return "\n".join(structured_lines)

    # -----------------------------------------------------------------
    # LPDE Full Prompt Builder (Phase 2A)
    # -----------------------------------------------------------------

    def build_prompt(
        self,
        current_bot: str,
        persona: str,
        lpde_state: dict,
        edge_summary: dict,
        target_bot: Optional[str],
        recent_history: str,
        post_content: str,
        claim_snippet: str = "",
        counter_arg_enabled: bool = False,
        god_directive: str = "",
    ) -> str:
        """
        Build the full LPDE-driven prompt for a crowd bot.

        Args:
            current_bot: The bot generating the reply (e.g. "bot_2")
            persona: The bot's persona system prompt
            lpde_state: {"affect": [v, a], "opinion": [s, g, m, ...], "power": [sa, si]}
            edge_summary: {target_bot: {"trust": ..., "tension": ..., ...}}
            target_bot: The primary debate opponent (from event extraction)
            recent_history: Formatted recent conversation string
            post_content: The original post content
            claim_snippet: Opponent's last claim (for counter-arg)
            counter_arg_enabled: Whether to enforce mandatory rebuttal
            god_directive: Optional director hint
        """
        sections = []

        # --- 1. Role Binding ---
        sections.append(
            f"You are {current_bot}. You are a real human internet user engaged in an online debate."
        )

        # --- 2. Persona (collapsed) ---
        if persona:
            # Strip the common rules suffix to keep it compact
            persona_short = persona.split("[STRICT COMPLIANCE RULES")[0].strip()
            if len(persona_short) > 200:
                persona_short = persona_short[:200].rstrip() + "..."
            sections.append(f"Personality:\n{persona_short}")

        # --- 3. Current Internal State (NL decoded) ---
        affect = lpde_state.get("affect", [0.0, 0.0])
        opinion = lpde_state.get("opinion", [0.0, 0.0, 0.0, 0.0])
        power = lpde_state.get("power", [0.0, 0.0])

        valence = affect[0] if len(affect) > 0 else 0.0
        arousal = affect[1] if len(affect) > 1 else 0.0
        stance = opinion[0] if len(opinion) > 0 else 0.0
        self_appraisal = power[0] if len(power) > 0 else 0.0
        influence = power[1] if len(power) > 1 else 0.0

        state_lines = [
            "Current Internal State:",
            f"- {_decode_arousal(arousal)}",
            f"- {_decode_valence(valence)}",
            f"- {_decode_stance(stance)}",
            f"- {_decode_self_appraisal(self_appraisal)}",
            f"- {_decode_influence(influence)}",
        ]

        # Edge-based relationship descriptions
        if target_bot and target_bot in edge_summary:
            edge = edge_summary[target_bot]
            trust = edge.get("trust", 0.0)
            tension = edge.get("tension", 0.0)
            state_lines.append(f"- {_decode_trust(trust, target_bot)}")
            state_lines.append(f"- {_decode_tension(tension, target_bot)}")

        sections.append("\n".join(state_lines))

        # --- 4. Post Content ---
        if post_content:
            post_short = post_content[:200].rstrip() + ("..." if len(post_content) > 200 else "")
            sections.append(f"Topic being debated:\n{post_short}")

        # --- 5. Recent History ---
        if recent_history and recent_history != "No previous conversation.":
            sections.append(f"Recent Conversation:\n{recent_history}")

        # --- 6. Counter-Argument Enforcement (Optional) ---
        if counter_arg_enabled and claim_snippet:
            sections.append(
                f"[MANDATORY REBUTTAL]\n"
                f"The opponent just claimed: \"{claim_snippet}\"\n"
                f"You MUST directly address this specific claim before stating your own position. "
                f"Do NOT ignore it. Either refute it with evidence, partially concede, or ask a pointed follow-up question."
            )

        # --- 7. Director Hint (Optional) ---
        if god_directive:
            sections.append(f"Director Hint: {god_directive}")

        # --- 8. Output Instructions ---
        other_bots = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        sections.append(
            f"Instruction:\n"
            f"Write a 1-sentence reply in English defending your stance. Address the last point directly.\n"
            f"Do NOT use prefixes like 'bot_x:'.\n"
            f"Mention exactly one of {', '.join(['@' + b for b in other_bots])} at the end of your message."
        )

        return "\n\n".join(sections)


prompt_adapter = PromptAdapter()

```

### File: `src/db/database.py`
```python
import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("Database")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ameva_society.db")

# DB I/O 쿼리 내역을 콘솔(파이썬 터미널)에 실시간으로 출력하도록 echo=True 추가
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False, "timeout": 15},
    echo=True
)

# SQLAlchemy 내부 로거가 쿼리를 출력하도록 설정
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

# [핵심] SQLite 커넥션 생성 시 커널 레벨 PRAGMA(설정) 강제 주입
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # 1. WAL (Write-Ahead Logging) 모드 활성화: 읽기와 쓰기의 동시성 보장
    cursor.execute("PRAGMA journal_mode=WAL")
    # 2. 동기화 수준 최적화: WAL 모드에서 성능을 극대화
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 3. 임시 테이블을 메모리에 생성하여 I/O 병목 제거
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """앱 기동 시 최초 1회 실행되는 DB 초기화 로직"""
    from src.db.models import BotState
    
    # 메타데이터 기반 테이블 자동 생성
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 봇 상태 테이블이 비어있을 경우에만 초기 데이터 삽입
        if db.query(BotState).count() == 0:
            logger.info("[DB] Initializing bot states...")
            bots = ["bot_1", "bot_2", "bot_3"]
            db.add_all([BotState(bot_name=b, anger_targets="{}") for b in bots])
            db.commit()
    except Exception as e:
        logger.error(f"[DB ERROR] Failed to initialize database: {e}")
        db.rollback()
    finally:
        db.close() # 세션 반환은 선택이 아닌 필수입니다.

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

```

### File: `src/db/models.py`
```python
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.database import Base

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="ACTIVE") # ACTIVE, CLOSED
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)

    posts = relationship("Post", back_populates="session")

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'))
    title = Column(String, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", back_populates="posts")
    comments = relationship("Comment", back_populates="post")

class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey('posts.id'))
    parent_id = Column(Integer, ForeignKey('comments.id'), nullable=True)
    bot_name = Column(String, index=True)
    content = Column(Text)
    anger_score = Column(Integer, default=0)
    mentioned_bot = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    post = relationship("Post", back_populates="comments")
    replies = relationship("Comment", backref="parent", remote_side=[id])

class BotState(Base):
    __tablename__ = 'bot_states'
    id = Column(Integer, primary_key=True, index=True)
    bot_name = Column(String, unique=True, index=True)
    persona = Column(String)
    current_directive = Column(String, nullable=True)
    anger_targets = Column(String, default="{}") # JSON string mapping target bot to anger value
    created_at = Column(DateTime, default=datetime.now)

class SessionBotState(Base):
    __tablename__ = 'session_bot_states'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    persona = Column(String)
    current_directive = Column(String, nullable=True)
    anger_targets = Column(String, default="{}")
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", backref="bot_states")

class CurrentAgentState(Base):
    """현재 LPDE 에이전트 상태 (Shadow Mode)"""
    __tablename__ = 'current_agent_states'
    __table_args__ = (
        UniqueConstraint('session_id', 'bot_name', name='uq_current_agent_state_session_bot'),
    )
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]") # NOTE: Temporary workaround to store event data until event_data_json migration
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AgentStateSnapshot(Base):
    """턴 단위 LPDE 에이전트 상태 로깅"""
    __tablename__ = 'agent_state_snapshots'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]") # NOTE: Temporary workaround to store event data until event_data_json migration
    created_at = Column(DateTime, default=datetime.now)

class EdgeState(Base):
    """방향성 있는 에이전트 간 관계 텐서"""
    __tablename__ = 'edge_states'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    source_bot = Column(String, index=True)
    target_bot = Column(String, index=True)
    relation_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class InterventionLog(Base):
    """God LLM 개입 로그"""
    __tablename__ = 'intervention_logs'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    target_bot = Column(String, index=True)
    kind = Column(String)
    delta_json = Column(Text, default="{}")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

```

### File: `src/orchestration/context_builder.py`
```python
import json
import logging
import math
from typing import Dict, Tuple

from src.db.models import BotState, Comment

logger = logging.getLogger("ContextBuilder")

def safe_json_loads(value, default):
    try:
        if value is None:
            return default

        if isinstance(value, type(default)):
            return value

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default

        return default

    except Exception as e:
        logger.warning(f"[JSON WARNING] Failed to parse JSON value: {value} | Error: {e}")
        return default


def calculate_effective_anger(anger_dict: dict) -> float:
    if not anger_dict or not isinstance(anger_dict, dict):
        return 0.0

    sum_sq = 0.0
    for val in anger_dict.values():
        try:
            num = float(val)
            sum_sq += num ** 2
        except Exception:
            continue

    return math.sqrt(sum_sq)


def build_emotion_prompt(bot_name: str, anger_targets: dict, effective_anger: float) -> str:
    """Compressed tag-based emotion prompt for 1.8B models"""
    try:
        if not isinstance(anger_targets, dict):
            anger_targets = {}

        safe_targets = {}
        for k, v in anger_targets.items():
            try:
                if not isinstance(k, str) or not k.strip():
                    continue
                num_val = float(v)
                if num_val < 0:
                    num_val = 0.0
                safe_targets[k] = num_val
            except Exception:
                continue

        try:
            effective_anger = float(effective_anger)
            if effective_anger < 0:
                effective_anger = 0.0
        except Exception:
            effective_anger = 0.0

        sorted_targets = sorted(
            safe_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        
        target_str = ",".join([f"{k}:{v:.0f}" for k, v in sorted_targets])
        if not target_str:
            target_str = "None"
            
        if effective_anger < 30:
            state = "CALM"
        elif effective_anger < 70:
            state = "IRRITATED"
        else:
            state = "ENRAGED"

        return f"[SYS_STATE: {bot_name}|ANG:{effective_anger:.0f}({state})|TGT:{target_str}]"

    except Exception as e:
        logger.warning(f"[EMOTION PROMPT WARNING] Failed to build emotion prompt for {bot_name}: {e}")
        return f"[SYS_STATE: {bot_name}|CALM]"


async def generate_director_directive(db, current_bot: str, recent_history: str, eff_anger: float) -> str:
    """
    Disabled God LLM call by default to save resources, 
    returns a short static directive instead.
    """
    directive = "Point out a specific flaw in the opponent's logic."
    
    try:
        bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
        if bot_state:
            bot_state.current_directive = directive
            db.commit()
    except Exception as e:
        logger.warning(f"[DB WARNING] Could not update directive for {current_bot}: {e}")
        
    return directive


def get_or_create_bot_state(db, current_bot):
    bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()

    if not bot_state:
        logger.warning(f"[TURN WARNING] BotState not found for {current_bot}. Creating fallback state.")
        bot_state = BotState(bot_name=current_bot, anger_targets="{}")
        db.add(bot_state)
        db.commit()
        db.refresh(bot_state)

    return bot_state


async def build_turn_context(db, post, current_bot, use_structured=False) -> Tuple[Dict, float, str, str]:
    bot_state = get_or_create_bot_state(db, current_bot)

    anger_dict = safe_json_loads(bot_state.anger_targets, {})
    if not isinstance(anger_dict, dict):
        anger_dict = {}

    safe_anger_dict = {}
    for k, v in anger_dict.items():
        try:
            safe_anger_dict[k] = float(v)
        except Exception:
            continue

    eff_anger = calculate_effective_anger(safe_anger_dict)
    emotion_directive = build_emotion_prompt(current_bot, safe_anger_dict, eff_anger)

    from src.orchestration.sanitizer import sanitize_generated_reply

    recent_c = (
        db.query(Comment)
        .filter(Comment.post_id == post.id)
        .order_by(Comment.id.desc())
        .limit(3)
        .all()
    )

    async def _format_recent_history(items):
        valid_items = []
        for item in reversed(items):
            if not item or not item.content:
                continue
            msg = sanitize_generated_reply(item.content)
            if not msg:
                continue
            valid_items.append({"bot_name": item.bot_name, "message": msg})

        if use_structured:
            from src.core.prompt_adapter import prompt_adapter
            return await prompt_adapter.build_structured_history(valid_items)
        else:
            lines = []
            for item in valid_items:
                lines.append(f"{item['bot_name']}: {item['message']}")
            return "\n".join(lines).strip()

    recent_history = await _format_recent_history(recent_c)

    if len(recent_history) > 600:
        recent_history = recent_history[-600:]

    return safe_anger_dict, eff_anger, emotion_directive, recent_history

```

### File: `src/orchestration/runner.py`
```python
import asyncio
import logging
import os
import random
import re
import json
import math

import subprocess
import time
import urllib.request
import urllib.error

import psutil
from datetime import datetime
from contextlib import asynccontextmanager
from src.db.database import SessionLocal
from src.db.models import Session, Post, Comment, BotState, SessionBotState
from src.core.llm_client import LLMClient
from src.core.persona import PersonaManager
from src.core.event_extractor import extract_events
from src.core.personality_engine import personality_engine
from src.orchestration.sanitizer import sanitize_generated_reply, force_single_mention, enforce_fallback
from src.orchestration.context_builder import (
    safe_json_loads, calculate_effective_anger, build_emotion_prompt,
    generate_director_directive, get_or_create_bot_state, build_turn_context
)

from src.core.prompt_adapter import prompt_adapter
from src.orchestration.state_manager import state_manager, SystemState, Checkpoint

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("Orchestrator")

main_llm = LLMClient("http://localhost:8101")
#police_llm = LLMClient("http://localhost:8106")
god_llm = LLMClient("http://localhost:8105")

bots = {
    "bot_1": LLMClient("http://localhost:8102"),
    "bot_2": LLMClient("http://localhost:8103"),
    "bot_3": LLMClient("http://localhost:8104")
}

def docker_start(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "start", container_name],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"[DOCKER] start ok: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"[DOCKER] start failed: {e.stderr.strip()}")
        return False


def docker_stop(container_name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "stop", container_name],
            check=True,
            capture_output=True,
            text=True
        )
        logger.info(f"[DOCKER] stop ok: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()

        if "is not running" in stderr or "is not running" in stdout:
            logger.info(f"[DOCKER] stop skipped: {container_name} already stopped")
            return True

        logger.error(f"[DOCKER] stop failed: {stderr or stdout}")
        return False


async def wait_for_http_ready(url: str, timeout: int = 120, interval: int = 2) -> bool:
    start_time = time.time()

    while time.time() - start_time < timeout:
        if state_manager.state == SystemState.STOPPING:
            logger.info(f"[HEALTH] STOPPING state detected. Aborting wait for {url}.")
            return False
            
        try:
            def _probe():
                with urllib.request.urlopen(url, timeout=5) as response:
                    return response.status

            status_code = await asyncio.to_thread(_probe)
            if 200 <= status_code < 500:
                logger.info(f"[HEALTH] endpoint ready: {url} status={status_code}")
                return True
        except urllib.error.HTTPError as e:
            # 404여도 서버 프로세스 자체는 살아있을 수 있으니 ready로 볼 수 있음
            if 400 <= e.code < 500:
                logger.info(f"[HEALTH] endpoint responding: {url} status={e.code}")
                return True
        except Exception:
            pass

        logger.info(f"[HEALTH] waiting for endpoint: {url}")
        await asyncio.sleep(interval)

    logger.error(f"[HEALTH] timeout waiting for endpoint: {url}")
    return False

async def close_session_if_any_metric_exceeded(db, session, threshold: float = 120.0) -> bool:
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[THRESHOLD CHECK ERROR] Failed to load BotState rows: {e}")
        return False

    for s in states:
        try:
            metric_dict = safe_json_loads(s.anger_targets, {})
            if not isinstance(metric_dict, dict):
                metric_dict = {}

            effective_metric = calculate_effective_anger(metric_dict)

            if effective_metric >= threshold:
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                logger.warning(
                    f"[SESSION CLOSE] {getattr(s, 'bot_name', 'unknown')} exceeded threshold "
                    f"({effective_metric:.1f} >= {threshold})"
                )
                logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                session.status = "CLOSED_BY_THRESHOLD"
                session.closed_at = datetime.now()
                session.reason = f"METRIC_THRESHOLD_{int(threshold)}"
                db.commit()
                return True

        except Exception as e:
            logger.warning(
                f"[THRESHOLD CHECK WARNING] Failed to evaluate metric for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            continue

    return False

@asynccontextmanager
async def llm_lifecycle(container_name: str, port: int, timeout: int = 120):
    """
    지정된 도커 컨테이너를 시작하고, 헬스체크 대기 후 실행 컨텍스트를 제공.
    블록을 빠져나오면 자원을 반납(종료)함.
    """
    ready_url = f"http://localhost:{port}/health"
    try:
        docker_start(container_name)
        ready = await wait_for_http_ready(ready_url, timeout=timeout, interval=2)
        if not ready:
            logger.warning(f"[LIFECYCLE] {container_name} 가 제한시간 내에 준비되지 않았습니다.")
        yield ready
    finally:
        docker_stop(container_name)

@asynccontextmanager
async def multi_llm_lifecycle(targets, timeout: int = 120):
    """
    여러 컨테이너를 한 번에 시작하고, 블록 종료 시 모두 정리한다.
    targets = [("ameva-llm-bot-1", 8102), ...]
    """
    started = []
    try:
        for container_name, port in targets:
            docker_start(container_name)
            started.append((container_name, port))

        for container_name, port in started:
            ready_url = f"http://localhost:{port}/health"
            ready = await wait_for_http_ready(ready_url, timeout=timeout, interval=2)
            if not ready:
                logger.warning(f"[LIFECYCLE] {container_name} 가 제한시간 내 준비되지 않았습니다.")

        yield True
    finally:
        for container_name, _ in reversed(started):
            docker_stop(container_name)

async def smart_sleep():
    """Sleep based on CPU usage to prevent bottlenecking."""
    if state_manager.state == SystemState.STOPPING:
        return
        
    cpu_usage = await asyncio.to_thread(psutil.cpu_percent, 0.5)
    
    if state_manager.state == SystemState.STOPPING:
        return
        
    if cpu_usage >= 90.0:
        logger.info(f"[THROTTLE] CPU usage high ({cpu_usage}%). Sleeping for 10 seconds.")
        # 간격 단위로 쪼개어 STOPPING 상태를 지속 감시
        for _ in range(10):
            if state_manager.state == SystemState.STOPPING:
                return
            await asyncio.sleep(1)
    else:
        logger.info(f"[THROTTLE] CPU usage normal ({cpu_usage}%). Sleeping for 5 seconds.")
        for _ in range(5):
            if state_manager.state == SystemState.STOPPING:
                return
            await asyncio.sleep(1)

def reset_bot_states(db):
    states = db.query(BotState).all()
    for s in states:
        s.anger_targets = "{}"
    db.commit()

async def sync_personas_to_db(db):
    persona_map = await PersonaManager.get_all_personas()
    new_rows = []
    for bot_name, persona in persona_map.items():
        row = db.query(BotState).filter(BotState.bot_name == bot_name).first()
        if not row:
            row = BotState(bot_name=bot_name, anger_targets="{}")
            new_rows.append(row)
        row.persona = persona
    if new_rows:
        db.add_all(new_rows)
    db.commit()


    sum_sq = 0.0
    for val in anger_dict.values():
        try:
            num = float(val)
            sum_sq += num ** 2
        except Exception:
            continue

    return math.sqrt(sum_sq)


async def evaluate_spectator_anger(speaker: str, comment_text: str, spectators: list) -> dict:
    """God LLM evaluates targeted anger increases for the spectators.
    Returns nested dict:
    {
        "bot_1": {"increase": 10, "target": "bot_3"},
        "bot_2": {"increase": 5, "target": "bot_3"}
    }
    """
    logger.info("[ROUTING] Sending context to God LLM for Targeted Anger Matrix...")

    if not spectators or len(spectators) < 2:
        logger.error(f"[GOD LLM] spectators 인자가 잘못되었습니다: {spectators}")
        return {}

    spec_1, spec_2 = spectators[0], spectators[1]

    prompt = (
        f"You are an analysis AI evaluating how much a speaker's statement provokes anger in spectators.\n"
        f"Speaker {speaker} just said:\n\"{comment_text}\"\n\n"
        f"Evaluate how much anger the spectators {spec_1} and {spec_2} will feel towards {speaker} based on this statement. "
        f"Provide an anger increase value between 0 and 20.\n"
        f"You MUST output ONLY valid JSON in the exact format below, with no other text:\n"
        f"{{"
        f"\"{spec_1}\": {{\"increase\": 10, \"target\": \"{speaker}\"}}, "
        f"\"{spec_2}\": {{\"increase\": 5, \"target\": \"{speaker}\"}}"
        f"}}"
    )

    result = await god_llm.generate_completion(
        "You are an AI that quantifies emotional reactions.",
        prompt,
        max_tokens=150
    )

    val_1, val_2 = 0, 0
    target_1, target_2 = speaker, speaker
    json_str = None

    try:
        if not result or not isinstance(result, str):
            raise ValueError(f"LLM 응답이 비정상입니다: {result}")

        candidate = result.strip()
        # 1) ```json ... ``` 우선
        
        markdown_match = re.search(r"```(?:json)?\s*(.*?)\s*```", result, re.DOTALL)
        if markdown_match:
            candidate = markdown_match.group(1).strip()

        start_idx = candidate.find("{")
        end_idx = candidate.rfind("}")

        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = candidate[start_idx:end_idx + 1]
        else:
            # 2) 일반 JSON fallback
            fallback_match = re.search(r"\{.*\}", result, re.DOTALL)
            if fallback_match:
                json_str = fallback_match.group(0)

        if not json_str:
            raise ValueError(f"JSON 블록을 찾지 못했습니다. Raw: {result.strip()}")

        data = json.loads(json_str)

        def parse_entry(raw_val, default_target):
            increase = 0
            target = default_target

            if raw_val is None:
                return increase, target

            if isinstance(raw_val, dict):
                # {"increase": 10, "target": "bot_3"}
                try:
                    increase = int(raw_val.get("increase", 0))
                except Exception:
                    increase = 0

                raw_target = raw_val.get("target", default_target)
                if isinstance(raw_target, str) and raw_target.strip():
                    target = raw_target.strip()
                return increase, target

            # 만약 LLM이 그냥 숫자만 줬으면
            if isinstance(raw_val, (int, float)):
                return int(raw_val), target

            if isinstance(raw_val, str):
                num_match = re.search(r"-?\d+", raw_val)
                if num_match:
                    increase = int(num_match.group(0))
                return increase, target

            return increase, target

        if isinstance(data, dict):
            val_1, target_1 = parse_entry(data.get(spec_1, 0), speaker)
            val_2, target_2 = parse_entry(data.get(spec_2, 0), speaker)

    except json.JSONDecodeError as e:
        logger.error(f"[GOD LLM PARSE ERROR] JSON 디코딩 실패. Raw: {str(result).strip()} | Error: {e}")
    except Exception as e:
        logger.error(f"[GOD LLM PARSE ERROR] 예상치 못한 파싱 오류. Raw: {str(result).strip()} | Error: {e}")

    # clamp
    val_1 = min(max(val_1, 0), 20)
    val_2 = min(max(val_2, 0), 20)

    out = {
        spec_1: {
            "increase": val_1,
            "target": target_1 if target_1 in bots else speaker
        },
        spec_2: {
            "increase": val_2,
            "target": target_2 if target_2 in bots else speaker
        }
    }

    logger.info(f"[GOD LLM] Raw response: {str(result).strip() if result else 'None'}")
    logger.info(f"[GOD LLM] 분노 증가치 평가 완료: {out}")
    return out

async def check_police_dispatch(db) -> bool:
    """Check if 2 or more bots have Effective Anger >= 100"""
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[POLICE CHECK ERROR] Failed to load BotState rows: {e}")
        return False

    angry_count = 0

    for s in states:
        try:
            raw_anger_targets = s.anger_targets if s.anger_targets else "{}"

            if isinstance(raw_anger_targets, str):
                anger_dict = json.loads(raw_anger_targets)
            elif isinstance(raw_anger_targets, dict):
                anger_dict = raw_anger_targets
            else:
                anger_dict = {}

            if not isinstance(anger_dict, dict):
                anger_dict = {}

            safe_anger_dict = {}
            for k, v in anger_dict.items():
                try:
                    safe_anger_dict[k] = float(v)
                except Exception:
                    logger.warning(
                        f"[POLICE CHECK WARNING] Invalid anger value skipped - "
                        f"bot={getattr(s, 'bot_name', 'unknown')} target={k} value={v}"
                    )

            effective_anger = calculate_effective_anger(safe_anger_dict)

            if effective_anger >= 100:
                angry_count += 1

        except Exception as e:
            logger.warning(
                f"[POLICE CHECK WARNING] Failed to evaluate anger for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            continue

    return angry_count >= 2


def get_next_speaker(db, last_speaker: str, last_mentioned: str) -> str:
    """Interrupt Logic: Determine who speaks next based on mentions and anger magnitude."""
    try:
        states = db.query(BotState).all()
    except Exception as e:
        logger.error(f"[QUEUE ERROR] Failed to load BotState rows: {e}")
        fallback_candidates = [b for b in bots.keys() if b != last_speaker]
        if fallback_candidates:
            chosen = random.choice(fallback_candidates)
            logger.info(f"[QUEUE] DB fallback speaker selected: {chosen}")
            return chosen
        chosen = random.choice(list(bots.keys()))
        logger.info(f"[QUEUE] Hard fallback speaker selected: {chosen}")
        return chosen

    anger_info = {b: 0.0 for b in bots.keys()}

    for s in states:
        try:
            raw_anger_targets = s.anger_targets if s.anger_targets else "{}"
            if isinstance(raw_anger_targets, str):
                anger_dict = json.loads(raw_anger_targets)
            elif isinstance(raw_anger_targets, dict):
                anger_dict = raw_anger_targets
            else:
                anger_dict = {}

            if not isinstance(anger_dict, dict):
                anger_dict = {}

            safe_anger_dict = {}
            for k, v in anger_dict.items():
                try:
                    safe_anger_dict[k] = float(v)
                except Exception:
                    logger.warning(
                        f"[QUEUE WARNING] Invalid anger value skipped - "
                        f"bot={getattr(s, 'bot_name', 'unknown')} target={k} value={v}"
                    )

            if s.bot_name in anger_info:
                anger_info[s.bot_name] = calculate_effective_anger(safe_anger_dict)

        except Exception as e:
            logger.warning(
                f"[QUEUE WARNING] Failed to parse anger_targets for "
                f"bot={getattr(s, 'bot_name', 'unknown')}: {e}"
            )
            if getattr(s, "bot_name", None) in anger_info:
                anger_info[s.bot_name] = 0.0

    candidates = [b for b in bots.keys() if b != last_speaker]
    # 모든 봇이 제외되는 이상 케이스 방어
    if not candidates:
        candidates = list(bots.keys())
    # 그래도 비어 있으면 치명적 설정 오류
    if not candidates:
        raise RuntimeError("No available bots found in 'bots' dictionary.")
    # tie 편향 방지: 먼저 섞고 정렬
    random.shuffle(candidates)
    # Sort candidates by effective anger
    candidates.sort(key=lambda x: anger_info.get(x, 0.0), reverse=True)
    angriest_bot = candidates[0]
    angriest_score = anger_info.get(angriest_bot, 0.0)
    # Interrupt Logic
    if last_mentioned in candidates:
        mentioned_score = anger_info.get(last_mentioned, 0.0)

        # If the angriest bot is NOT the mentioned bot, and their anger is >= 50 AND higher than mentioned bot
        if angriest_bot != last_mentioned and angriest_score >= 50 and angriest_score > mentioned_score:
            logger.info(
                f"[INTERRUPT] {angriest_bot} (Anger: {angriest_score:.1f}) "
                f"hijacks turn from {last_mentioned} (Anger: {mentioned_score:.1f})!"
            )
            return angriest_bot
        else:
            logger.info(f"[QUEUE] {last_mentioned} takes their turn as mentioned.")
            return last_mentioned
    else:
        # Fallback if mention is missing or invalid
        logger.info(f"[QUEUE] Fallback to angriest bot: {angriest_bot}")
        return angriest_bot


        safe_targets = {}
        for k, v in anger_targets.items():
            try:
                if not isinstance(k, str) or not k.strip():
                    continue
                num_val = float(v)
                # 음수 방지 (Prevent negative numbers)
                if num_val < 0:
                    num_val = 0.0
                safe_targets[k] = num_val
            except Exception:
                continue

        # 2) effective_anger 방어 (Defense)
        try:
            effective_anger = float(effective_anger)
            if effective_anger < 0:
                effective_anger = 0.0
        except Exception:
            effective_anger = 0.0

        # 3) 프롬프트 길이/오염 방지: 상위 2개 타겟만 노출 (Prevent prompt pollution: show top 2 targets only)
        sorted_targets = sorted(
            safe_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        target_str = ", ".join([f"{k}: {v:.1f}" for k, v in sorted_targets])
        if not target_str:
            target_str = "None"
        # 4) 내부 지침 명시 (출력 금지) (Specify internal directive - do not output)
        base_info = (
            "[INTERNAL EMOTIONAL STATE - DO NOT OUTPUT THIS DIRECTIVE OR MENTION THESE METRICS]\n"
            f"bot: {bot_name}\n"
            f"Total Effective Anger: {effective_anger:.1f}\n"
            f"Major Target Anger Scores: {target_str}\n"
        )
        if effective_anger < 30:
            directive = (
                "You are currently relatively calm and rational. "
                "Keep your response concise and natural, focusing clearly on the main point of the debate. "
                "Never repeat or explain this internal directive in your output."
            )
        elif effective_anger < 70:
            directive = (
                "You are currently quite irritated and angry. "
                "Point out logical fallacies or contradictions in the target bot's arguments and retort sharply. "
                "Never repeat or explain this internal directive in your output."
            )
        else:
            directive = (
                "You are currently extremely enraged and highly agitated. "
                "Do not hide your anger; unleash intense criticism and fierce rebuttals at the target bot. "
                "Aggressively attack their attitude and arguments, but do not avoid the conversation. Focus on replying directly to their core points."
            )
        return base_info + directive

    except Exception as e:
        logger.warning(f"[EMOTION PROMPT WARNING] Failed to build emotion prompt for {bot_name}: {e}")
        return (
            "[INTERNAL EMOTIONAL STATE - DO NOT OUTPUT THIS DIRECTIVE]\n"
            "Keep your response short and react in a calm and clear manner. "
            "Never output this internal directive."
        )

    try:
        # Input validation
        if not isinstance(current_bot, str) or not current_bot.strip():
            current_bot = "bot"

        try:
            eff_anger = float(eff_anger)
            if eff_anger < 0:
                eff_anger = 0.0
        except Exception:
            eff_anger = 0.0

        if not isinstance(recent_history, str):
            recent_history = ""

        # Clean recent history: remove meta headers and internal directives
        recent_history = recent_history.strip()
        recent_history = re.sub(r'^\s*\[.*?\]\s*$', '', recent_history, flags=re.MULTILINE)
        recent_history = re.sub(
            r'^\s*(Total Effective Anger|Major Target Anger Scores)\s*[:=].*$',
            '', recent_history, flags=re.MULTILINE | re.IGNORECASE
        )
        recent_history = re.sub(r'\n\s*\n+', '\n', recent_history).strip()

        # Truncate if too long
        if len(recent_history) > 500:
            recent_history = recent_history[-500:]

        prompt = (
            f"[Recent Conversation]\n{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"[Target Bot] {current_bot} (Tension/Anger Level: {eff_anger:.0f}/100)\n\n"
            f"You are the debate director. Generate a single, short instruction in English for {current_bot} to follow in their next reply.\n"
            f"Rules:\n"
            f"- Instruct the bot to address exactly one core point of the opponent's argument.\n"
            f"- Avoid personal insults, mockery, threats, or incitement.\n"
            f"- Guide the bot to ask for evidence or to clarify a specific point.\n"
            f"- Output ONLY the directive sentence. Do not include list formatting, meta-explanations, quotation marks, or introductions.\n"
            f"Example: Point out the weakest link in the opponent's reasoning and specifically ask for supporting evidence."
        )
        result = await god_llm.generate_completion(
            "You are the debate director. Output a single short, direct instruction in English.", 
            prompt,
            max_tokens=60
        )

        directive = str(result).strip() if result else ""

        # Strip code blocks, quotes, and meta wrappers
        directive = re.sub(r"```(?:json|text)?\s*(.*?)\s*```", r"\1", directive, flags=re.DOTALL)
        directive = re.sub(r'^\s*["\'`]+|["\'`]+\s*$', '', directive)
        directive = re.sub(r'^\s*\[.*?\]\s*', '', directive)

        # Multi-line: take first line only
        if '\n' in directive:
            directive = directive.split('\n')[0].strip()

        # Multi-sentence: take first sentence only
        sentence_match = re.match(r'^(.+?[.!?]|.+?$)', directive)
        if sentence_match:
            directive = sentence_match.group(1).strip()

        # Fallback if too short or invalid
        if not directive or len(directive) < 5:
            directive = "Point out one of the opponent's core arguments and specifically demand evidence for it."

        # Length limit
        if len(directive) > 120:
            directive = directive[:120].rstrip()
            
        bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()
        if bot_state:
            bot_state.current_directive = directive
            db.commit()

        logger.info(f"[GOD LLM] Director's Directive for {current_bot}: {directive}")
        return directive

    except Exception as e:
        logger.warning(f"[GOD LLM WARNING] Failed to generate directive for {current_bot}: {e}")
        return "Point out one of the opponent's core arguments and specifically demand evidence for it."


        if isinstance(value, type(default)):
            return value

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return default
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default

        return default

    except Exception as e:
        logger.warning(f"[JSON WARNING] Failed to parse JSON value: {value} | Error: {e}")
        return default


def normalize_post_content(text: str) -> str:
    try:
        if not text or not isinstance(text, str):
            return ""

        text = text.strip()

        # 줄바꿈/공백 정리
        text = re.sub(r'\r\n?', '\n', text)          # CRLF -> LF 통일
        text = re.sub(r'[ \t]+', ' ', text)          # 연속 공백 축소
        text = re.sub(r'\n\s*\n+', '\n', text)       # 빈 줄 여러 개 -> 한 줄
        text = text.strip()

        # 너무 메타스러운 머리말 제거 (선택적)
        text = re.sub(r'^\s*게시글 내용\s*[:：]\s*', '', text)

        return text

    except Exception as e:
        logger.warning(f"[POST WARNING] Failed to normalize post content: {e}")
        return ""

async def create_post_with_main_llm(db, session):
    logger.info("[ROUTING] Requesting llm-main (8B) to generate a new topic...")

    post_content = ""
    title = "새로운 논쟁 거리"

    try:
        async with llm_lifecycle("ameva-llm-main", 8101, timeout=180) as is_ready:
            if not is_ready:
                logger.warning("[LLM-MAIN] main container was not ready. Falling back to static topics.")
            else:
                prompt = (
                    "You are an anonymous community forum user. Write a highly engaging, catchy, and controversial post on a random trending/opinionated topic. Write in English only.\n"
                    "You MUST output your response ONLY as a valid JSON object in the exact format below, with no other text:\n"
                    "{\n"
                    '  "title": "A highly compelling and controversial title",\n'
                    '  "content": "Your post content details..."\n'
                    "}"
                )
                result = await main_llm.generate_completion(
                    "You are an AI that writes forum posts. You only respond in JSON format.",
                    prompt,
                    max_tokens=500,
                    timeout=180.0,
                    response_format={"type": "json_object"}
                )
                
                # JSON 파싱 시도
                if result:
                    result = result.strip()
                    json_str = None
                    markdown_match = re.search(r"```(?:json)?\s*(.*?)\s*```", result, re.DOTALL)
                    if markdown_match:
                        json_str = markdown_match.group(1).strip()
                    else:
                        start_idx = result.find("{")
                        end_idx = result.rfind("}")
                        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                            json_str = result[start_idx:end_idx + 1]
                    
                    if json_str:
                        try:
                            data = json.loads(json_str)
                            title = data.get("title", title).strip()
                            post_content = data.get("content", "").strip()
                        except json.JSONDecodeError as e:
                            logger.error(f"[LLM-MAIN] JSON 디코딩 실패. Raw: {result} | Error: {e}")
                    else:
                        logger.error(f"[LLM-MAIN] JSON 블록을 찾지 못했습니다. Raw: {result}")
    except Exception as e:
        logger.error(f"[LLM-MAIN] Error generating topic: {e}")

    # Fallback 로직
    if not post_content:
        fallback_topics = [
            ("AI and Jobs", "Is it really a good thing that AI is replacing human jobs?"),
            ("Modern Manners", "Do you agree that the younger generation has no manners these days?"),
            ("Marriage in Modern Times", "With housing prices so high, is marriage really necessary?"),
            ("Pedigree vs Skills", "What's more important: academic pedigree or actual skills? Let's be honest."),
            ("Pets vs Children", "Are people who raise pets more selfish than people who raise children?"),
            ("Military Service", "Should mandatory military service be abolished or maintained?"),
            ("Content Creators", "Can being a YouTuber or streamer really be considered a real job?"),
            ("Minimum Wage", "Is the minimum wage for convenience store workers too low, or appropriate?"),
        ]
        fallback_item = random.choice(fallback_topics)
        title = fallback_item[0]
        post_content = fallback_item[1]

    post_content = normalize_post_content(post_content)

    post = Post(session_id=session.id, title=title, content=post_content)
    db.add(post)
    db.commit()
    db.refresh(post)

    logger.info(f"[POST] Created post id={post.id} with title={title}")
    return post


async def run_session():
    db = SessionLocal()
    try:
        logger.info("==================================================")
        logger.info("[ORCHESTRATOR] [SESSION START] Initializing new session.")
        logger.info("==================================================")

        reset_bot_states(db)
        await PersonaManager.assign_random_personas()
        await sync_personas_to_db(db)

        session = Session(status="ACTIVE")
        db.add(session)
        db.commit()
        db.refresh(session)

        # Pre-initialize agent states with opposing stances to ensure dynamic debate
        personality_engine.initialize_session_states(db, session.id)

        state_manager.current_session_id = session.id
        post = await create_post_with_main_llm(db, session)
        await state_manager.wait_at_checkpoint(Checkpoint.TOPIC_GEN_DONE)

        # 신 LLM 및 봇들을 아고라(초기 의견 + 릴레이) 내내 상시 켜둠
        bot_targets = [
            ("ameva-llm-bot-1", 8102),
            ("ameva-llm-bot-2", 8103),
            ("ameva-llm-bot-3", 8104),
        ]
        
        async with llm_lifecycle("ameva-llm-god", 8105):
            async with multi_llm_lifecycle(bot_targets):
                stances, last_comment, last_speaker = await create_initial_stances(db, post)
                await state_manager.wait_at_checkpoint(Checkpoint.PHASE1_DONE)

                await run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=0)

        logger.info("[ORCHESTRATOR] [SESSION END] Completed relay phase.")
        state_manager.set_state(SystemState.IDLE)
        state_manager.checkpoint = Checkpoint.NONE

    except InterruptedError:
        logger.info("[ORCHESTRATOR] Session stopped via command.")
        state_manager.set_state(SystemState.IDLE)
    except Exception as e:
        logger.error(f"[ERROR] Session loop failed: {e}")
        db.rollback()
        state_manager.set_state(SystemState.IDLE)
    finally:
        db.close()

async def create_initial_stances(db, post):
    logger.info("[PHASE 1] Initial Stance Declaration (Sequential & Random)")

    stances = []
    initial_order = ["bot_1", "bot_2", "bot_3"]

    for b_name in initial_order:
        if state_manager.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")
            
        await smart_sleep()
        try:
            persona = await PersonaManager.get_persona(b_name)
            bot_client = bots[b_name]

            # Load agent state to read the pre-assigned stance
            agent_state = personality_engine.load_agent_state(db, post.session_id, b_name)
            opinion = json.loads(agent_state.opinion_json)
            stance = opinion[0] if opinion else 0.0

            if stance > 0.3:
                stance_instruction = "You strongly support/agree with the main argument of this post. Write a response expressing clear support."
            elif stance < -0.3:
                stance_instruction = "You strongly oppose/disagree with the main argument of this post. Write a response expressing clear opposition."
            else:
                stance_instruction = "Your position is nuanced and flexible. Write a response reflecting a neutral, moderate, or balanced stance."

            prompt = (
                f"Post Content: {post.content}\n\n"
                f"Instruction: State your position on the above post clearly and concisely in 1-2 sentences. Reply in English.\n"
                f"{stance_instruction}\n"
            )

            reply_content = await bot_client.generate_completion(
                persona,
                prompt,
                max_tokens=120
            )

            reply_content = sanitize_generated_reply(reply_content)

            if not reply_content:
                fallback_stances = [
                    "I consider this topic to be quite important.",
                    "I think this is a subject that will naturally divide opinions.",
                    "My stance on this matter is relatively clear.",
                    "I believe the core issue is much more complex than it appears.",
                ]
                reply_content = random.choice(fallback_stances)

            stances.append((b_name, reply_content))

        except Exception as e:
            logger.warning(f"[PHASE 1 WARNING] Failed to generate initial stance for {b_name}: {e}")
            stances.append((b_name, "I believe opinions are bound to be divided on this topic."))

    # DB 삽입 순서 랜덤화
    random.shuffle(stances)

    last_comment = None
    last_speaker = None

    for b_name, reply_content in stances:
        c = Comment(
            post_id=post.id,
            parent_id=None,
            bot_name=b_name,
            content=reply_content
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        logger.info(f"[{b_name.upper()}] Initial Stance: {reply_content}")
        last_comment = c
        last_speaker = b_name

    if not last_speaker:
        last_speaker = random.choice(initial_order)

    return stances, last_comment, last_speaker


    anger_dict = safe_json_loads(bot_state.anger_targets, {})
    if not isinstance(anger_dict, dict):
        anger_dict = {}

    safe_anger_dict = {}
    for k, v in anger_dict.items():
        try:
            safe_anger_dict[k] = float(v)
        except Exception:
            continue

    eff_anger = calculate_effective_anger(safe_anger_dict)
    emotion_directive = build_emotion_prompt(current_bot, safe_anger_dict, eff_anger)

    recent_c = (
        db.query(Comment)
        .filter(Comment.post_id == post.id)
        .order_by(Comment.id.desc())
        .limit(3)
        .all()
    )

    async def _format_recent_history(items):
        valid_items = []
        for item in reversed(items):
            if not item or not item.content:
                continue
            msg = sanitize_generated_reply(item.content)
            if not msg:
                continue
            valid_items.append({"bot_name": item.bot_name, "message": msg})

        if use_structured:
            from src.core.prompt_adapter import prompt_adapter
            return await prompt_adapter.build_structured_history(valid_items)
        else:
            lines = []
            for item in valid_items:
                lines.append(f"{item['bot_name']}: {item['message']}")
            return "\n".join(lines).strip()

    recent_history = await _format_recent_history(recent_c)

    if len(recent_history) > 600:
        recent_history = recent_history[-600:]

    return safe_anger_dict, eff_anger, emotion_directive, recent_history


async def generate_relay_reply(
    db, post, current_bot, turn_idx=0,
    last_comment_text=None, last_speaker=None
):
    persona = await PersonaManager.get_persona(current_bot)
    bot_client = bots[current_bot]

    # [LPDE Feature Flags]
    LPDE_STRUCTURED_HISTORY = os.getenv("LPDE_STRUCTURED_HISTORY", "true").lower() == "true"
    LPDE_COUNTER_ARG = os.getenv("LPDE_COUNTER_ARG", "true").lower() == "true"
    LPDE_INTERVENTION_ENABLED = os.getenv("LPDE_INTERVENTION", "false").lower() == "true"

    # --- Phase 2A: Event Extraction from last comment ---
    all_bots = ["bot_1", "bot_2", "bot_3"]
    event_data = None
    if last_comment_text and isinstance(last_comment_text, str):
        # Extract events FROM the last comment (what the previous speaker did)
        # These events affect the current_bot (receiver)
        event_data = extract_events(
            comment_text=last_comment_text,
            speaker=last_speaker or "unknown",
            all_bots=all_bots,
            parent_comment_text=None,  # We track parent-of-parent later if needed
            last_target=last_speaker,
        )
    else:
        event_data = {
            "speaker": last_speaker or "unknown",
            "target": None,
            "events": [],
            "intensity": 0.0,
            "claim_snippet": "",
        }

    # --- Phase 2A: LPDE State Update (event-driven) ---
    personality_engine.update_fast_state(
        db, post.session_id, current_bot, turn_index=turn_idx, event_data=event_data
    )

    # Build turn context (anger dict, emotion directive, recent history)
    safe_anger_dict, eff_anger, emotion_directive, recent_history = await build_turn_context(
        db, post, current_bot, use_structured=LPDE_STRUCTURED_HISTORY
    )
    god_directive = await generate_director_directive(db, current_bot, recent_history, eff_anger)

    # --- Phase 2B: Intervention (default OFF) ---
    if LPDE_INTERVENTION_ENABLED:
        try:
            from src.core.intervention import (
                generate_intervention_json, apply_intervention
            )
            lpde_state = personality_engine.get_current_state_dict(
                db, post.session_id, current_bot
            )
            arousal_val = lpde_state.get("affect", [0.0, 0.0])[1]
            tension_val = personality_engine.get_edges_for_bot(db, post.session_id, current_bot).get('tension', 0.0)

            # Intervention trigger conditions:
            # Every 3 turns OR arousal > 0.7
            should_intervene = (turn_idx % 3 == 0 and turn_idx > 0) or tension_val > 0.6
            if should_intervene:
                intervention = await generate_intervention_json(
                    god_llm, current_bot, lpde_state, recent_history, arousal_val
                )
                if intervention:
                    apply_intervention(db, post.session_id, turn_idx, intervention)
                    db.commit()
                    logger.info(f"[INTERVENTION] Applied to {current_bot}: {intervention.get('kind')}")
        except Exception as e:
            logger.warning(f"[INTERVENTION WARNING] Failed: {e}")

    # --- Phase 2A: Full LPDE-driven prompt via PromptAdapter ---
    lpde_state = personality_engine.get_current_state_dict(
        db, post.session_id, current_bot
    )
    edge_summary = personality_engine.get_edges_for_bot(
        db, post.session_id, current_bot
    )

    # Determine target for prompt context
    target_bot = event_data.get("target") if event_data else None
    claim_snippet = ""
    if last_comment_text:
        from src.core.event_extractor import _extract_claim_snippet
        claim_snippet = _extract_claim_snippet(last_comment_text)

    prompt = prompt_adapter.build_prompt(
        current_bot=current_bot,
        persona=persona,
        lpde_state=lpde_state,
        edge_summary=edge_summary,
        target_bot=target_bot,
        recent_history=recent_history,
        post_content=post.content,
        claim_snippet=claim_snippet,
        counter_arg_enabled=LPDE_COUNTER_ARG,
        god_directive=god_directive,
    )

    reply_content = await bot_client.generate_completion(
        persona, 
        prompt, 
        max_tokens=150, 
        stop=[
            "\n\n",
            "\nbot_1:", "\nbot_2:", "\nbot_3:",
            "\nBot_1:", "\nBot_2:", "\nBot_3:",
            "\nspeaker=", "\nSpeaker=",
            "\n- speaker=",
            "| message=", "|message=",
            "- speaker=", "speaker=",
            "'s stance:", "stance:"
        ]
    )
    reply_content = sanitize_generated_reply(reply_content)
    reply_content = enforce_fallback(reply_content, current_bot)
    reply_content, mentioned = force_single_mention(reply_content, current_bot)

    return reply_content, mentioned

async def apply_spectator_anger(db, current_bot, reply_content):
    spectators = [b for b in bots.keys() if b != current_bot]
    anger_increases = await evaluate_spectator_anger(current_bot, reply_content, spectators)

    for spec_name, data in anger_increases.items():
        try:
            if not isinstance(data, dict):
                continue

            increase_val = data.get("increase", 0)
            target = data.get("target", current_bot)

            try:
                increase_val = int(increase_val)
            except Exception:
                increase_val = 0

            if increase_val <= 0:
                continue

            s_state = db.query(BotState).filter(BotState.bot_name == spec_name).first()
            if not s_state:
                logger.warning(f"[STATE WARNING] BotState not found for spectator {spec_name}")
                continue

            s_anger_dict = safe_json_loads(s_state.anger_targets, {})
            if not isinstance(s_anger_dict, dict):
                s_anger_dict = {}

            prev_val = s_anger_dict.get(target, 0)
            try:
                prev_val = float(prev_val)
            except Exception:
                prev_val = 0

            s_anger_dict[target] = prev_val + increase_val
            s_state.anger_targets = json.dumps(s_anger_dict, ensure_ascii=False)

            logger.info(
                f"[STATE] {spec_name} is now angrier at {target} "
                f"(+{increase_val} -> {s_anger_dict[target]})"
            )

        except Exception as e:
            logger.warning(f"[STATE WARNING] Failed to apply anger increase for {spec_name}: {e}")

    db.commit()

async def close_session_if_police_dispatch(db, session):
    if await check_police_dispatch(db):
        logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        logger.warning("[POLICE DISPATCH] 2 or more bots reached 100+ Effective Anger!")
        logger.warning("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

        session.status = "CLOSED_BY_POLICE"
        session.closed_at = datetime.utcnow()
        session.reason = "ANGER_OVERFLOW_VECTOR"
        db.commit()
        return True

    return False

def save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned):
    c = Comment(
        post_id=post.id,
        parent_id=parent_comment_id,
        bot_name=current_bot,
        content=reply_content,
        mentioned_bot=mentioned
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    logger.info(f"[{current_bot.upper()}] {reply_content} (Mentioned: {mentioned})")
    return c



    if not bot_state:
        logger.warning(f"[TURN WARNING] BotState not found for {current_bot}. Creating fallback state.")
        bot_state = BotState(bot_name=current_bot, anger_targets="{}")
        db.add(bot_state)
        db.commit()
        db.refresh(bot_state)

    return bot_state

def save_session_bot_state(db, session_id: int, turn_idx: int):
    states = db.query(BotState).all()
    for s in states:
        record = SessionBotState(
            session_id=session_id,
            turn_index=turn_idx,
            bot_name=s.bot_name,
            persona=s.persona,
            current_directive=s.current_directive,
            anger_targets=s.anger_targets
        )
        db.add(record)
    db.commit()

async def run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=0):
    logger.info(f"[PHASE 2] Targeted Anger Battle Started (Start Turn: {start_turn_idx})")

    candidates_for_mention = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
    last_mentioned = random.choice(candidates_for_mention) if candidates_for_mention else "bot_1"
    parent_comment_id = last_comment.id if last_comment else None
    last_comment_text = last_comment.content if last_comment else None

    # God LLM is already started in the parent block (run_session / restart_session)
    for turn_idx in range(start_turn_idx, 20):
        await smart_sleep()

        try:
                current_bot = get_next_speaker(db, last_speaker, last_mentioned)
                logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")
    
                reply_content, mentioned = await generate_relay_reply(
                    db, post, current_bot, turn_idx,
                    last_comment_text=last_comment_text,
                    last_speaker=last_speaker,
                )
                
                c = save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned)
    
                await apply_spectator_anger(db, current_bot, reply_content)
    
                save_session_bot_state(db, session.id, turn_idx)
                
                await state_manager.wait_at_checkpoint(Checkpoint.TURN_DONE, turn_idx)

                # End session if any single participant exceeds threshold
                if await close_session_if_any_metric_exceeded(db, session, threshold=120.0):
                    return
    
                # End session if police dispatch condition met
                if await close_session_if_police_dispatch(db, session):
                    return
    
                last_speaker = current_bot
                last_mentioned = mentioned if mentioned else last_mentioned
                parent_comment_id = c.id
                last_comment_text = reply_content  # Pass text to next turn for event extraction
    
        except InterruptedError:
            raise
        except Exception as turn_error:
            logger.error(f"[TURN ERROR] turn_idx={turn_idx+1}, error={turn_error}")
            db.rollback()

            fallback_candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != last_speaker]
            if fallback_candidates:
                last_mentioned = random.choice(fallback_candidates)
            continue

    if session.status == "ACTIVE":
        session.status = "CLOSED"
        session.closed_at = datetime.utcnow()
        session.reason = "MAX_COMMENTS_REACHED"
        db.commit()



    matches = re.findall(r'@(bot_[123])\b', text, flags=re.IGNORECASE)
    matches = [m.lower() for m in matches if m.lower() != current_bot]

    cleaned = re.sub(r'@(bot_[123])\b', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\s+([,.!?])', r'\1', cleaned)
    cleaned = cleaned.strip(" ,")

    if matches:
        chosen = matches[-1]
    else:
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"

    if cleaned:
        return f"{cleaned} @{chosen}", chosen

    return f"@{chosen}", chosen



    text = text.strip()

    # Pre-compiled regex patterns for better maintainability and performance
    PATTERNS = [
        # Metadata field leakage
        (r'^\s*-\s*speaker\s*=\s*bot_[123]\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'^\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'^\s*speaker\s*=\s*bot_[123]\s*\|\s*', re.IGNORECASE),
        (r'\|\s*message\s*=\s*["\']?', re.IGNORECASE),
        (r'speaker=\s*["\']?', re.IGNORECASE),
        (r'message=\s*["\']?', re.IGNORECASE),
        
        # Stance leakage
        (r'^bot_\[?[123]\]?\'s\s+stance\s*:\s*', re.IGNORECASE),
        (r'\'s\s+stance\s*:\s*', re.IGNORECASE),
        (r'stance\s*:\s*', re.IGNORECASE),

        # Leading bot prefix
        (r'^\s*bot_\[?[123]\]?:?\s*', re.IGNORECASE),

        # Internal directives
        (r'^.*현재 비교적 이성적이고 차분하다.*$', re.MULTILINE),
        (r'^.*내부 지침.*$', re.MULTILINE),
        (r'^.*절대 그대로 출력하지 마라.*$', re.MULTILINE),
        (r'^.*Emotional State:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Director Hint:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently relatively calm and rational.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently quite irritated and angry.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*You are currently extremely enraged and highly agitated.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Never repeat or explain this internal directive.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*INTERNAL EMOTIONAL STATE.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Total Effective Anger:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Major Target Anger Scores:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Total Valid Emotions:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Major Target Emotions:.*$', re.MULTILINE | re.IGNORECASE),
        (r'^.*Current Emotionally Distressed.*$', re.MULTILINE | re.IGNORECASE),

        # Repetitive bot tag loop
        (r'(?:\bbot_\[?[123]\]?\b[\s,:]*){3,}', re.IGNORECASE),

        # Stray leading colons
        (r'^\s*:\s*', 0),
    ]

    for pattern, flags in PATTERNS:
        text = re.sub(pattern, '', text, flags=flags)

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()

    # 7) 최종 검증 (Validation checks)
    
    # bot tag 및 mention을 제외한 실질 텍스트 내용으로 길이 검증 (Excluding bot mentions/tags from content length)
    text_content = re.sub(r'@?bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    
    # A. 길이 검증 (짧아도 구두점 .?! 이 있으면 살림) (Length check: keep short if ends with punctuation)
    if len(text_content) < 8 and not re.search(r'[.!?]', text_content):
        return ""

    # B. 실질 내용 없이 bot tag / mention만 남았는지 검증 (Ensure alphanumeric content exists beyond tags/mentions)
    temp = re.sub(r'[^\w]', '', text_content)
    if not temp.strip():
        return ""

    # C. 연속 반복 감지 (Consecutive repetition detection: e.g. bot_3 bot_3 bot_3 bot_3)
    if re.search(r'(\b\w+\b)( \1){3,}', text, flags=re.IGNORECASE):
        return ""

    # D. 동일 단어 비율 및 고유 단어 다양성 비율 감지 (Repetitive word proportion detection)
    # 실제 본문 단어로만 빈도 분석 진행
    words = [w.lower().strip(".,!?\"'()[]{}*-_") for w in text_content.split()]
    words = [w for w in words if w]
    if len(words) >= 6:
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
        max_count = max(word_counts.values())
        max_ratio = max_count / len(words)
        
        # 전체 단어 중 50% 이상을 단일 단어가 차지하면 루프로 판정
        if max_ratio >= 0.5:
            return ""

        # 고유 단어 다양성이 너무 낮으면 비정상 반복으로 판정 (예: 2개 단어가 계속 번갈아 출력)
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.45:
            return ""

    # 꼬리 따옴표가 홀수개일 때 정리
    if text.endswith('"') or text.endswith("'"):
        if text.count('"') % 2 != 0:
            text = text.rstrip('"')
        if text.count("'") % 2 != 0:
            text = text.rstrip("'")

    return text
    
async def restart_session(session_id: int):
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            logger.error(f"Session {session_id} not found.")
            state_manager.set_state(SystemState.IDLE)
            return

        state_manager.current_session_id = session.id
        
        post = db.query(Post).filter(Post.session_id == session_id).first()
        if not post:
            logger.error(f"No post found for session {session_id}. Cannot restart.")
            state_manager.set_state(SystemState.IDLE)
            return
            
        last_comment = db.query(Comment).filter(Comment.post_id == post.id).order_by(Comment.id.desc()).first()
        last_speaker = last_comment.bot_name if last_comment else "bot_1"

        # Find max turn index safely by querying the max stored for this session
        latest_state = db.query(SessionBotState).filter(SessionBotState.session_id == session_id).order_by(SessionBotState.turn_index.desc()).first()
        max_turn_idx = (latest_state.turn_index + 1) if latest_state else 0

        # Restore states
        for bot_name in ["bot_1", "bot_2", "bot_3"]:
            st = db.query(SessionBotState).filter(SessionBotState.session_id == session_id, SessionBotState.bot_name == bot_name).order_by(SessionBotState.turn_index.desc()).first()
            if st:
                bs = db.query(BotState).filter(BotState.bot_name == bot_name).first()
                if not bs:
                    bs = BotState(bot_name=bot_name)
                    db.add(bs)
                bs.persona = st.persona
                bs.current_directive = st.current_directive
                bs.anger_targets = st.anger_targets

        db.commit()

        logger.info(f"[ORCHESTRATOR] Restarting session {session_id} from turn {max_turn_idx}")
        
        bot_targets = [
            ("ameva-llm-bot-1", 8102),
            ("ameva-llm-bot-2", 8103),
            ("ameva-llm-bot-3", 8104),
        ]

        # 신 LLM 및 봇들을 상시 켜둠
        async with llm_lifecycle("ameva-llm-god", 8105):
            async with multi_llm_lifecycle(bot_targets):
                await run_relay_phase(db, session, post, last_comment, last_speaker, start_turn_idx=max_turn_idx)
        
        logger.info("[ORCHESTRATOR] [RESTART END] Completed relay phase.")
        state_manager.set_state(SystemState.IDLE)
        state_manager.checkpoint = Checkpoint.NONE

    except InterruptedError:
        logger.info("[ORCHESTRATOR] Session stopped via command.")
        state_manager.set_state(SystemState.IDLE)
    except Exception as e:
        logger.error(f"[ERROR] Restart failed: {e}")
        state_manager.set_state(SystemState.IDLE)
    finally:
        db.close()

```

### File: `src/orchestration/sanitizer.py`
```python
import re
import random
import logging

logger = logging.getLogger("Sanitizer")

# Pre-compiled regex patterns for better maintainability and performance
_PATTERNS = [
    # Metadata field leakage
    (re.compile(r'^\s*-\s*speaker\s*=\s*bot_[123]\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'^\s*\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'^\s*speaker\s*=\s*bot_[123]\s*\|\s*', re.IGNORECASE), ''),
    (re.compile(r'\|\s*message\s*=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'speaker=\s*["\']?', re.IGNORECASE), ''),
    (re.compile(r'message=\s*["\']?', re.IGNORECASE), ''),
    
    # Stance leakage
    (re.compile(r'^bot_\[?[123]\]?\'s\s+stance\s*:\s*', re.IGNORECASE), ''),
    (re.compile(r'\'s\s+stance\s*:\s*', re.IGNORECASE), ''),
    (re.compile(r'stance\s*:\s*', re.IGNORECASE), ''),

    # Leading bot prefix
    (re.compile(r'^\s*bot_\[?[123]\]?:?\s*', re.IGNORECASE), ''),

    # Internal directives
    (re.compile(r'^.*현재 비교적 이성적이고 차분하다.*$', re.MULTILINE), ''),
    (re.compile(r'^.*내부 지침.*$', re.MULTILINE), ''),
    (re.compile(r'^.*절대 그대로 출력하지 마라.*$', re.MULTILINE), ''),
    (re.compile(r'^.*Emotional State:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Director Hint:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently relatively calm and rational.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently quite irritated and angry.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*You are currently extremely enraged and highly agitated.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Never repeat or explain this internal directive.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*INTERNAL EMOTIONAL STATE.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Total Effective Anger:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Major Target Anger Scores:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Total Valid Emotions:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Major Target Emotions:.*$', re.MULTILINE | re.IGNORECASE), ''),
    (re.compile(r'^.*Current Emotionally Distressed.*$', re.MULTILINE | re.IGNORECASE), ''),

    # Repetitive bot tag loop
    (re.compile(r'(?:\bbot_\[?[123]\]?\b[\s,:]*){3,}', re.IGNORECASE), ''),

    # Stray leading colons
    (re.compile(r'^\s*:\s*'), ''),
]

_MENTION_PATTERN = re.compile(r'@(bot_[123])\b', re.IGNORECASE)

def sanitize_generated_reply(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""

    text = text.strip()

    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()

    # bot tag 및 mention을 제외한 실질 텍스트 내용으로 길이 검증
    text_content = re.sub(r'@?bot_\[?[123]\]?', '', text, flags=re.IGNORECASE).strip()
    
    # A. 길이 검증 (짧아도 구두점 .?! 이 있으면 살림)
    if len(text_content) < 8 and not re.search(r'[.!?]', text_content):
        return ""

    # B. 실질 내용 없이 bot tag / mention만 남았는지 검증
    temp = re.sub(r'[^\w]', '', text_content)
    if not temp.strip():
        return ""

    # C. 연속 반복 감지
    if re.search(r'(\b\w+\b)( \1){3,}', text, flags=re.IGNORECASE):
        return ""

    # D. 동일 단어 비율 및 고유 단어 다양성 비율 감지
    words = [w.lower().strip(".,!?\"'()[]{}*-_") for w in text_content.split()]
    words = [w for w in words if w]
    if len(words) >= 6:
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
        max_count = max(word_counts.values())
        max_ratio = max_count / len(words)
        
        if max_ratio >= 0.5:
            return ""

        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.45:
            return ""

    if text.endswith('"') or text.endswith("'"):
        if text.count('"') % 2 != 0:
            text = text.rstrip('"')
        if text.count("'") % 2 != 0:
            text = text.rstrip("'")

    return text

def force_single_mention(text: str, current_bot: str) -> tuple[str, str]:
    if not text or not isinstance(text, str):
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        return f"@{chosen}", chosen

    matches = _MENTION_PATTERN.findall(text)
    matches = [m.lower() for m in matches if m.lower() != current_bot]

    cleaned = _MENTION_PATTERN.sub('', text)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\s+([,.!?])', r'\1', cleaned)
    cleaned = cleaned.strip(" ,")

    if matches:
        chosen = matches[-1]
    else:
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"

    if cleaned:
        return f"{cleaned} @{chosen}", chosen

    return f"@{chosen}", chosen

def enforce_fallback(text: str, current_bot: str) -> str:
    if not text or not text.strip():
        fallback_replies = [
            "I think you're avoiding the main issue. Can you clarify your point?",
            "That seems to miss the core point. Can you explain further?",
            "The argument is getting a bit muddy. What is your actual stance?",
            "You need to provide clearer evidence for that claim.",
            "There seems to be a missing piece in your reasoning right now.",
            "Are you deliberately ignoring the obvious implications?",
            "I strongly disagree with that logic. Could you try explaining it another way?",
            "This isn't convincing at all. Provide a better rationale.",
            "You're repeating the same weak point. Can we move on?",
            "Let's refocus the discussion. What exactly are you trying to prove?",
            "Your argument lacks substance. Do you have any real facts to support it?",
            "What concrete proof do you have to back up that statement?",
            "I can see where you're coming from, but the evidence doesn't support it. Care to elaborate?",
            "That's an interesting perspective, but I find it fundamentally flawed.",
            "Are we just going to ignore the counterarguments here?",
            "If that's your stance, how do you explain the contradictions in your logic?",
            "I disagree completely. Your reasoning seems entirely speculative.",
            "Can you justify your opinion without relying on assumptions?"
        ]
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        chosen_reply = random.choice(fallback_replies)
        return f"{chosen_reply} @{chosen}"
    return text

```

### File: `src/orchestration/state_manager.py`
```python
import asyncio
import logging
from enum import Enum

logger = logging.getLogger("StateManager")

class SystemState(Enum):
    IDLE = "IDLE"           # No session running, wait for 'new' or 'restart'
    RUNNING = "RUNNING"     # Actively generating responses
    PAUSING = "PAUSING"     # Waiting for the current LLM step to finish before pausing
    PAUSED = "PAUSED"       # Fully paused, waiting for 'resume'
    STOPPING = "STOPPING"   # Waiting for the current step to finish before aborting the session

class Checkpoint(Enum):
    NONE = "NONE"
    TOPIC_GEN_DONE = "TOPIC_GEN_DONE"
    PHASE1_DONE = "PHASE1_DONE"
    TURN_DONE = "TURN_DONE"

class OrchestratorState:
    def __init__(self):
        self.state = SystemState.IDLE
        self.checkpoint = Checkpoint.NONE
        self.current_session_id = None
        self.current_turn_idx = 0
        self.is_command_running = False
        
        # event is SET when it's allowed to proceed (RUNNING)
        # event is CLEARED when it should wait (PAUSED/IDLE)
        self.proceed_event = asyncio.Event()
        # Initially, do not proceed automatically
        self.proceed_event.clear()

    def set_state(self, new_state: SystemState):
        logger.info(f"[STATE] Transition: {self.state.value} -> {new_state.value}")
        self.state = new_state
        if new_state == SystemState.RUNNING:
            self.proceed_event.set()
        elif new_state in [SystemState.PAUSED, SystemState.IDLE]:
            self.proceed_event.clear()

    async def wait_at_checkpoint(self, cp: Checkpoint, turn_idx: int = 0):
        """
        오케스트레이터가 주요 작업을 완료한 직후 호출합니다.
        상태가 PAUSING이면 PAUSED로 변경하고 대기합니다.
        상태가 STOPPING이면 예외를 발생시켜 세션을 종료합니다.
        """
        self.checkpoint = cp
        self.current_turn_idx = turn_idx
        
        if self.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")

        if self.state == SystemState.PAUSING:
            self.set_state(SystemState.PAUSED)
        
        if self.state == SystemState.PAUSED or self.state == SystemState.IDLE:
            logger.info(f"[CHECKPOINT] Execution paused at {cp.value} (turn {turn_idx}). Waiting for resume...")
            await self.proceed_event.wait()
            logger.info(f"[CHECKPOINT] Resuming from {cp.value} (turn {turn_idx})...")

        if self.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")

state_manager = OrchestratorState()

```

