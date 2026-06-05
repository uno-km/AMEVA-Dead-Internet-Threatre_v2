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
      - LPDE_STRUCTURED_HISTORY=true
      - LPDE_FULL_PROMPT=false
      - LPDE_LEGACY_PROMPT=false
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
    command: -m /models/qwen2.5-0.5b.gguf -c 2048 --host 0.0.0.0 --port 8080
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
    command: -m /models/qwen2.5-0.5b.gguf -c 2048 --host 0.0.0.0 --port 8080
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
    command: -m /models/qwen2.5-0.5b.gguf -c 2048 --host 0.0.0.0 --port 8080
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
        return {"error": "실행 중인 세션이 없습니다."}
    if state_manager.state in [SystemState.PAUSING, SystemState.PAUSED]:
        return {"error": "이미 중단 중이거나 중단된 상태입니다."}
    state_manager.set_state(SystemState.PAUSING)
    return {"message": "Pausing session..."}

@app.post("/api/control/resume")
async def control_resume():
    if state_manager.state == SystemState.IDLE:
        return {"error": "진행 중인 세션이 없습니다. 경고: 새로 시작하거나 이어하기를 이용하세요."}
    if state_manager.state == SystemState.RUNNING:
        return {"error": "이미 실행 중입니다."}
    state_manager.set_state(SystemState.RUNNING)
    return {"message": "Session resumed"}

@app.post("/api/control/stop")
async def control_stop():
    if state_manager.state == SystemState.IDLE:
        return {"error": "실행 중인 세션이 없습니다."}
    state_manager.set_state(SystemState.STOPPING)
    return {"message": "Stopping session..."}

@app.post("/api/control/restart/{post_id}")
async def control_restart(post_id: int, db: DbSession = Depends(get_db)):
    if state_manager.state != SystemState.IDLE:
        return {"error": "명령어 수행중입니다. 동작 못합니다."}
        
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        return {"error": f"글 번호 {post_id}번을 찾을 수 없습니다."}
        
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

### File: `src/core/llm_client.py`
```python
import httpx
import logging

logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.timeout = 60.0

    async def generate_completion(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, stop=None) -> str:
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

        try:
            logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Max Tokens: {max_tokens})")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
            return cls._cache.get(bot_name, "너는 평화를 사랑하는 로봇이다.") + COMMON_RULES

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
        peace_prompt = "너는 평화를 사랑하는 로봇이다."
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
import json
import math
import logging
from typing import Dict, List, Any
from sqlalchemy.orm import Session
from datetime import datetime

from src.db.models import CurrentAgentState, AgentStateSnapshot, EdgeState

logger = logging.getLogger("LPDE")

class PersonalityEngine:
    """
    Layered Personality Dynamics Engine (LPDE)
    Week 1A MVP: 
    - Shadow Mode (상태만 계산/저장하고 실제 프롬프트에 즉각적인 구조 개편은 유보)
    - 기저 성격(Traits)은 상수로, Affect(2D), Opinion(4D), Power(2D)만 업데이트
    """
    def __init__(self):
        # MVP용 기본 가중치 (추후 학습 또는 정교한 BFI-2 매핑으로 대체)
        self.clip_min = -1.0
        self.clip_max = 1.0

    def _clip(self, val: float) -> float:
        return max(self.clip_min, min(self.clip_max, val))

    def _sigmoid_bound(self, val: float) -> float:
        """비선형 활성화: 폭주를 막기 위해 tanh(val) 사용"""
        return math.tanh(val)

    def load_agent_state(self, db: Session, session_id: int, bot_name: str) -> CurrentAgentState:
        """기존 DB에서 로드, 없으면 새로 생성"""
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
                affect_json=json.dumps([0.0, 0.0]), # [Valence, Arousal]
                memory_json=json.dumps([0.0] * 8), # [Issue commitment, etc]
                opinion_json=json.dumps([0.0, 0.0, 0.0, 0.0]), # [Stance, Gap, Moral]
                power_json=json.dumps([0.0, 0.0]), # [SelfAppraisal, SystemicInfluence]
                residual_json=json.dumps([0.0] * 16)
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    def update_fast_state(self, db: Session, session_id: int, bot_name: str, turn_index: int):
        """
        턴이 끝날 때마다 호출되어 상태 공간을 업데이트합니다.
        (현재는 난수 또는 단순 decay 기반의 MVP 로직이며, Week 1B의 Event 추출기가 완성되면 Edge 기반 업데이트 추가)
        """
        agent = self.load_agent_state(db, session_id, bot_name)
        
        # Parse current states
        affect = json.loads(agent.affect_json)
        opinion = json.loads(agent.opinion_json)
        power = json.loads(agent.power_json)

        # [MVP Logic] 
        # 임시로 자연스러운 Decay (0으로 회귀) 및 소규모 변동성 부여
        # Affect: Arousal은 약간씩 가라앉고, Valence는 중립으로 회귀
        new_affect = [
            self._clip(self._sigmoid_bound(affect[0] * 0.9)), # Valence decay
            self._clip(self._sigmoid_bound(affect[1] * 0.95)) # Arousal decay
        ]

        # Opinion: 자신의 입장을 고수하려는 관성(Inertia)
        new_opinion = [self._clip(o * 0.98) for o in opinion]

        # Power: 서서히 변동
        new_power = [self._clip(p * 0.99) for p in power]

        # 상태 업데이트
        agent.affect_json = json.dumps(new_affect)
        agent.opinion_json = json.dumps(new_opinion)
        agent.power_json = json.dumps(new_power)
        db.commit()

        # 스냅샷 저장
        self.snapshot(db, session_id, turn_index, agent)

        logger.info(f"[LPDE] Updated Shadow State for {bot_name}: Affect={new_affect}")

    def snapshot(self, db: Session, session_id: int, turn_index: int, agent: CurrentAgentState):
        """턴이 종료될 때 스냅샷 테이블에 기록"""
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
            residual_json=agent.residual_json
        )
        db.add(snap)
        db.commit()

personality_engine = PersonalityEngine()

```

### File: `src/core/prompt_adapter.py`
```python
import logging
from typing import List
from src.db.models import Comment

logger = logging.getLogger("PromptAdapter")

class PromptAdapter:
    """
    LLM이 이전 대화를 '대본(Script)'으로 착각하고 다른 봇의 발화를 이어쓰는 
    할루시네이션(Hallucination)을 막기 위해, 대화 기록을 메타데이터 형태로 구조화합니다.
    """
    def __init__(self):
        pass

    def build_structured_history(self, items: List[dict]) -> str:
        """
        기존 "bot_1: 텍스트" 형식을 탈피하고 구조화된 로그 형태로 변환합니다.
        items는 {"bot_name": ..., "message": ...} 형태의 딕셔너리 리스트입니다.
        출력 포맷: '- speaker=... | message="..."'
        """
        if not items:
            return "No previous conversation."

        structured_lines = ["[Conversation History]"]
        for item in items:
            bot_name = item.get("bot_name", "Unknown")
            msg = item.get("message", "").strip()
            import json
            msg_json = json.dumps(msg, ensure_ascii=False)
            # 봇 이름이나 사람 이름을 명확히 분리하고, message를 데이터 필드로 취급
            line = f'- speaker={bot_name} | message={msg_json}'
            structured_lines.append(line)
        
        return "\n".join(structured_lines)

    def build_prompt(self, agent_state, history: str, target_bot: str) -> str:
        """
        Week 1B에서 적용될 전체 프롬프트 빌더. 
        (1A에서는 Shadow Mode이므로 사용하지 않음)
        """
        pass

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
            for b in bots:
                db.add(BotState(bot_name=b, anger_targets="{}"))
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
    residual_json = Column(Text, default="[]")
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
    residual_json = Column(Text, default="[]")
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

### File: `src/orchestration/runner.py`
```python
import asyncio
import logging
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
    for bot_name, persona in persona_map.items():
        row = db.query(BotState).filter(BotState.bot_name == bot_name).first()
        if not row:
            row = BotState(bot_name=bot_name, anger_targets="{}")
            db.add(row)
        row.persona = persona
    db.commit()

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

def build_emotion_prompt(bot_name: str, anger_targets: dict, effective_anger: float) -> str:
    try:
        # 1) anger_targets 방어
        if not isinstance(anger_targets, dict):
            anger_targets = {}

        safe_targets = {}
        for k, v in anger_targets.items():
            try:
                if not isinstance(k, str) or not k.strip():
                    continue
                num_val = float(v)
                # 음수 방지
                if num_val < 0:
                    num_val = 0.0
                safe_targets[k] = num_val
            except Exception:
                continue

        # 2) effective_anger 방어
        try:
            effective_anger = float(effective_anger)
            if effective_anger < 0:
                effective_anger = 0.0
        except Exception:
            effective_anger = 0.0

        # 3) 프롬프트 길이/오염 방지: 상위 2개 타겟만 노출
        sorted_targets = sorted(
            safe_targets.items(),
            key=lambda x: x[1],
            reverse=True
        )[:2]
        target_str = ", ".join([f"{k}: {v:.1f}" for k, v in sorted_targets])
        if not target_str:
            target_str = "없음"
        # 4) 내부 지침임을 명시 (출력 금지)
        base_info = (
            "[내부 감정 지침 - 절대 그대로 출력하지 마라]\n"
            f"bot: {bot_name}\n"
            f"총합 유효 분노: {effective_anger:.1f}\n"
            f"주요 타겟 분노치: {target_str}\n"
        )
        if effective_anger < 30:
            directive = (
                "현재 비교적 이성적이고 차분하다. "
                "짧고 자연스럽게 말하되 논점만 분명하게 짚어라. "
                "내부 지침 문구를 그대로 복사하거나 설명하지 마라."
            )
        elif effective_anger < 70:
            directive = (
                "현재 꽤 화가 난 상태다. "
                "너를 자극한 타겟 봇을 향해 논리적인 모순을 제기하며 날카롭게 쏘아붙여라."
                "내부 지침 문구를 그대로 복사하거나 설명하지 마라."
            )
        else:
            directive = (
                "현재 극도로 분노하여 흥분한 상태, "
                "대로 감정을 감추지 말고, 타겟 봇에게 격정적인 비판과 반박을 쏟아부어라."
                "상대방의 태도나 주장을 거칠게 받아쳐라"
                "대화를 회피하지 말고 핵심 주장에 반응해라."
            )
        return base_info + directive

    except Exception as e:
        logger.warning(f"[EMOTION PROMPT WARNING] Failed to build emotion prompt for {bot_name}: {e}")
        return (
            "[내부 감정 지침 - 절대 그대로 출력하지 마라]\n"
            "차분하고 분명한 태도로 짧게 반응해라. "
            "내부 지침 문구를 그대로 출력하지 마라."
        )
async def generate_director_directive(db, current_bot: str, recent_history: str, eff_anger: float) -> str:
    """God LLM generates a short, safe directive for the current speaker based on conversation context."""
    logger.info(f"[GOD LLM] Generating dynamic director's directive for {current_bot}...")

    try:
        # 1) 입력값 방어
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

        # 2) 최근 대화 오염 제거 + 길이 제한
        recent_history = recent_history.strip()
        recent_history = re.sub(r'^\s*\[.*?\]\s*$', '', recent_history, flags=re.MULTILINE)  # 메타 헤더 제거
        recent_history = re.sub(r'^\s*(총합 유효 분노|주요 타겟 분노치|나의 총합 유효 분노|나의 타겟별 분노치)\s*[:：].*$', '', recent_history, flags=re.MULTILINE)
        recent_history = re.sub(r'\n\s*\n+', '\n', recent_history).strip()

        # 너무 길면 마지막 부분만 사용
        if len(recent_history) > 500:
            recent_history = recent_history[-500:]

        prompt = (
            f"[최근 대화]\n{recent_history if recent_history else '최근 대화 없음'}\n\n"
            f"[명령 대상] {current_bot} (긴장도: {eff_anger:.0f})\n\n"
            f"너는 토론 진행 보조자다. {current_bot}가 다음 댓글에서 사용할 짧은 지시를 "
            f"한국어 한 문장으로만 출력해라.\n"
            f"규칙:\n"
            f"- 상대의 핵심 주장 하나만 짚어라.\n"
            f"- 인신공격, 조롱, 위협, 선동은 금지한다.\n"
            f"- 근거를 요구하거나 논점을 명확히 하도록 유도해라.\n"
            f"- 메타 설명, 목록, 따옴표, 머리말 없이 한 문장만 출력해라.\n"
            f"예: 상대 주장 중 근거가 가장 약한 한 지점을 짚고, 그 근거를 구체적으로 요구해라."
        )
        result = await god_llm.generate_completion(
        "너는 갈등을 지시하는 감독관이다. 짧게 지시만 내려라.", 
            prompt,
            max_tokens=60
        )

        directive = str(result).strip() if result else ""

        # 3) 코드블록/따옴표/메타 제거
        directive = re.sub(r"```(?:json|text)?\s*(.*?)\s*```", r"\1", directive, flags=re.DOTALL)
        directive = re.sub(r'^\s*["“”\'`]+|["“”\'`]+\s*$', '', directive)
        directive = re.sub(r'^\s*\[.*?\]\s*', '', directive)
        directive = re.sub(r'^\s*(지시사항|출력|답변)\s*[:：]\s*', '', directive)

        # 4) 여러 줄이면 첫 줄만
        if '\n' in directive:
            directive = directive.split('\n')[0].strip()

        # 5) 여러 문장이면 첫 문장만
        sentence_match = re.match(r'^(.+?[.!?。]|.+?$)', directive)
        if sentence_match:
            directive = sentence_match.group(1).strip()

        # 6) 너무 짧거나 비정상이면 안전 fallback
        if not directive or len(directive) < 5:
            directive = "Point out one of the opponent's core arguments and specifically demand evidence for it."

        # 7) 길이 제한
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
        return "상대의 핵심 주장 하나를 짚고, 그 근거를 구체적으로 요구해라."

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

    try:
        async with llm_lifecycle("ameva-llm-main", 8101) as is_ready:
            if not is_ready:
                logger.warning("[LLM-MAIN] main container was not ready. Falling back to static topics.")
            else:
                post_content = await main_llm.generate_completion(
                    "You are an anonymous community forum user. Write a short, controversial post on a random topic. Write in English only.",
                    "Write a new post.",
                    max_tokens=300
                )
    except Exception as e:
        logger.error(f"[LLM-MAIN] Error generating topic: {e}")

    post_content = normalize_post_content(post_content)

    title = "새로운 논쟁 거리"
    if post_content:
        # Extract title if the LLM output something like **Title:** ...
        title_match = re.search(r'\*\*Title:\*\*\s*([^\n]+)', post_content, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            # Remove the title line from content
            post_content = re.sub(r'\*\*Title:\*\*\s*[^\n]+\n?', '', post_content, flags=re.IGNORECASE).strip()
        
        # Remove "Posted by: ..." if present
        post_content = re.sub(r'\*\*Posted by:\*\*\s*[^\n]+\n?', '', post_content, flags=re.IGNORECASE).strip()
    else:
        fallback_topics = [
            "Is it really a good thing that AI is replacing human jobs?",
            "Do you agree that the younger generation has no manners these days?",
            "With housing prices so high, is marriage really necessary?",
            "What's more important: academic pedigree or actual skills? Let's be honest.",
            "Are people who raise pets more selfish than people who raise children?",
            "Should mandatory military service be abolished or maintained?",
            "Can being a YouTuber or streamer really be considered a real job?",
            "Is the minimum wage for convenience store workers too low, or appropriate?",
        ]
        post_content = random.choice(fallback_topics)

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

            prompt = (
                f"Post Content: {post.content}\n\n"
                f"Instruction: State your position on the above post clearly and concisely in 1-2 sentences. Reply in English.\n"
            )

            reply_content = await bot_client.generate_completion(
                persona,
                prompt,
                max_tokens=120
            )

            reply_content = sanitize_generated_reply(reply_content)

            if not reply_content:
                fallback_stances = [
                    "나는 이 문제를 꽤 중요하게 본다.",
                    "이건 생각보다 의견이 갈릴 만한 주제다.",
                    "내 입장은 비교적 분명한 편이다.",
                    "겉보기보다 논점이 복잡한 문제라고 본다.",
                ]
                reply_content = random.choice(fallback_stances)

            stances.append((b_name, reply_content))

        except Exception as e:
            logger.warning(f"[PHASE 1 WARNING] Failed to generate initial stance for {b_name}: {e}")
            stances.append((b_name, "이 주제는 입장이 갈릴 수밖에 없다고 본다."))

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

def build_turn_context(db, post, current_bot, use_structured=False):
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

    recent_c = (
        db.query(Comment)
        .filter(Comment.post_id == post.id)
        .order_by(Comment.id.desc())
        .limit(3)
        .all()
    )

    def _format_recent_history(items):
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
            return prompt_adapter.build_structured_history(valid_items)
        else:
            lines = []
            for item in valid_items:
                lines.append(f"{item['bot_name']}: {item['message']}")
            return "\n".join(lines).strip()

    recent_history = _format_recent_history(recent_c)

    if len(recent_history) > 600:
        recent_history = recent_history[-600:]

    return safe_anger_dict, eff_anger, emotion_directive, recent_history


async def generate_relay_reply(db, post, current_bot, turn_idx=0):
    import os
    persona = await PersonaManager.get_persona(current_bot)
    bot_client = bots[current_bot]

    # [LPDE Feature Flags]
    LPDE_STRUCTURED_HISTORY = os.getenv("LPDE_STRUCTURED_HISTORY", "true").lower() == "true"
    LPDE_FULL_PROMPT = os.getenv("LPDE_FULL_PROMPT", "false").lower() == "true"
    LPDE_LEGACY_PROMPT = os.getenv("LPDE_LEGACY_PROMPT", "false").lower() == "true"

    # [LPDE Phase 1A] Shadow Mode Update
    from src.core.personality_engine import personality_engine
    personality_engine.update_fast_state(db, post.session_id, current_bot, turn_index=turn_idx)

    safe_anger_dict, eff_anger, emotion_directive, recent_history = build_turn_context(
        db, post, current_bot, use_structured=LPDE_STRUCTURED_HISTORY
    )
    god_directive = await generate_director_directive(db, current_bot, recent_history, eff_anger)

    if LPDE_FULL_PROMPT:
        # Phase 1B Placeholder: 추후 PromptAdapter를 활용해 완전히 구조화된 LPDE 프롬프트 생성 (현재는 임시 기능)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"[System] You are {current_bot}. Respond to the above conversation based on your internal LPDE state.\n"
        )
    elif LPDE_LEGACY_PROMPT:
        # 진짜 legacy prompt 유지 (Shadow Mode 비교용)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"Recent Conversation:\n{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"Instruction: State your opinion by either refuting or agreeing with the recent conversation in 1-2 sentences. Reply in English.\n"
            f"DO NOT write a chat script. DO NOT use 'bot_x:' prefixes. Just output your own statement directly.\n"
            f"You MUST mention exactly one of '@bot_1', '@bot_2', or '@bot_3' at the end of your message (do NOT mention yourself).\n"
        )
    else:
        # Phase 1A: 구조 강화된 prompt (shadow mode + hardening)
        prompt = (
            f"Post Content: {post.content}\n\n"
            f"Recent Conversation:\n{recent_history if recent_history else 'No recent conversation'}\n\n"
            f"Current Speaker: {current_bot}\n"
            f"Instruction: You are {current_bot}. "
            f"Respond ONLY as {current_bot} in 1-2 sentences in English.\n"
            f"Do NOT write dialogue for other bots. "
            f"Do NOT write a chat script. "
            f"Do NOT use 'bot_x:' prefixes. "
            f"Output only your own final message.\n"
            f"You MUST mention exactly one of '@bot_1', '@bot_2', or '@bot_3' at the end of your message (do NOT mention yourself).\n"
        )

        if god_directive:
            prompt += f"\nDirector Hint: {god_directive}\n"

        if emotion_directive:
            prompt += f"\nEmotional State: {emotion_directive}\n"

    reply_content = await bot_client.generate_completion(
        persona, 
        prompt, 
        max_tokens=150, 
        stop=[
            "\n\n",
            "\nbot_1:", "\nbot_2:", "\nbot_3:",
            "\nBot_1:", "\nBot_2:", "\nBot_3:",
            "\nspeaker=", "\nSpeaker=",
            "\n- speaker="
        ]
    )
    reply_content = sanitize_generated_reply(reply_content)

    if not reply_content:
        fallback_replies = [
            "That seems to miss the core point.",
            "The argument is getting a bit muddy.",
            "You need to provide clearer evidence for that.",
            "There seems to be a missing piece in your claim right now.",
        ]
        reply_content = random.choice(fallback_replies)

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


def get_or_create_bot_state(db, current_bot):
    bot_state = db.query(BotState).filter(BotState.bot_name == current_bot).first()

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
    port_map = {"bot_1": 8102, "bot_2": 8103, "bot_3": 8104}

    # 신 LLM은 상위 블록(run_session, restart_session)에서 이미 켜져 있음
    for turn_idx in range(start_turn_idx, 20):
        await smart_sleep()

        try:
                current_bot = get_next_speaker(db, last_speaker, last_mentioned)
                logger.info(f"--- TURN {turn_idx+1}: {current_bot.upper()} ---")
    
                reply_content, mentioned = await generate_relay_reply(db, post, current_bot, turn_idx)
                
                c = save_relay_comment(db, post, parent_comment_id, current_bot, reply_content, mentioned)
    
                await apply_spectator_anger(db, current_bot, reply_content)
    
                save_session_bot_state(db, session.id, turn_idx)
                
                await state_manager.wait_at_checkpoint(Checkpoint.TURN_DONE, turn_idx)

                # 1) 참가자 한 명이라도 metric >= 120 이면 세션 종료
                if await close_session_if_any_metric_exceeded(db, session, threshold=120.0):
                    return
    
                # 2) 기존 다중 participant 조건
                if await close_session_if_police_dispatch(db, session):
                    return
    
                last_speaker = current_bot
                last_mentioned = mentioned if mentioned else last_mentioned
                parent_comment_id = c.id
    
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


def force_single_mention(text: str, current_bot: str) -> tuple[str, str]:
    if not text or not isinstance(text, str):
        candidates = [b for b in ["bot_1", "bot_2", "bot_3"] if b != current_bot]
        chosen = random.choice(candidates) if candidates else "bot_1"
        return f"@{chosen}", chosen

    matches = re.findall(r'@(bot_\[?[123]\]?)(?!\d)', text, flags=re.IGNORECASE)
    # Normalize bot name by removing brackets for comparison
    matches = [re.sub(r'[\[\]]', '', m).lower() for m in matches]
    matches = [m for m in matches if m != current_bot]

    cleaned = re.sub(r'@(bot_\[?[123]\]?)(?!\d)', '', text, flags=re.IGNORECASE)
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

def sanitize_generated_reply(text: str) -> str:
    if not text or not isinstance(text, str):
        return ""
        
    # Remove hallucinated bot prefixes
    text = re.sub(r'^bot_\[?[123]\]?:\s*', '', text, flags=re.IGNORECASE)

    # 1) 내부 지침 헤더 라인 제거
    text = re.sub(
        r'^\s*\[(?:내부 감정 지침|나의 감정 상태)[^\]]*\]\s*$',
        '',
        text,
        flags=re.MULTILINE
    )
    # 2) 메타 정보 라인 제거
    text = re.sub(r'^\s*bot\s*:\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*총합 유효 분노\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*주요 타겟 분노치\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*나의 총합 유효 분노\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*나의 타겟별 분노치\s*[:：\-]?\s*.*$', '', text, flags=re.MULTILINE)
    # 3) 내부 지침 문장 자체 제거
    text = re.sub(
        r'^.*내부 지침.*그대로 출력하지 마라.*$',
        '',
        text,
        flags=re.MULTILINE
    )
    text = re.sub(
        r'^.*절대 그대로 출력하지 마라.*$',
        '',
        text,
        flags=re.MULTILINE
    )
    # 4) 불필요한 빈 줄/공백 정리
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text = text.strip()
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

