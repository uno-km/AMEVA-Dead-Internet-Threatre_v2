import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session as DbSession
import logging

from src.db.database import init_db, get_db
from src.db.models import Session, Post, Comment, BotState
from src.orchestration.runner import start_orchestrator_loop

templates = Jinja2Templates(directory="src/ui/templates")
logger = logging.getLogger("API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. DB 초기화
    init_db()
    logger.info("[System] Database initialized.")
    
    # 2. 백그라운드 루프(스레드/비동기 태스크) 가동
    asyncio.create_task(start_orchestrator_loop())
    logger.info("[System] Orchestrator loop started.")
    
    yield
    
    logger.info("[System] Shutting down AMEVA-DeadInternetSociety...")

app = FastAPI(title="AMEVA-DeadInternetSociety", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: DbSession = Depends(get_db)):
    """
    메인 게시판 UI 렌더링
    """
    # Fetch the most recent active session's post, or the latest post
    latest_session = db.query(Session).order_by(Session.id.desc()).first()
    posts_data = []
    
    if latest_session:
        post = db.query(Post).filter(Post.session_id == latest_session.id).first()
        if post:
            # comments where parent_id is Null (root comments)
            root_comments = db.query(Comment).filter(Comment.post_id == post.id, Comment.parent_id == None).order_by(Comment.created_at.asc()).all()
            
            # Fetch all child comments and map them
            all_comments = db.query(Comment).filter(Comment.post_id == post.id, Comment.parent_id != None).order_by(Comment.created_at.asc()).all()
            replies_map = {}
            for c in all_comments:
                if c.parent_id not in replies_map:
                    replies_map[c.parent_id] = []
                replies_map[c.parent_id].append(c)

            posts_data.append({
                "id": post.id,
                "title": post.title,
                "content": post.content,
                "created_at": post.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "session_status": latest_session.status,
                "root_comments": root_comments,
                "replies_map": replies_map
            })

    import json
    from src.orchestration.runner import calculate_effective_anger
    bot_states_db = db.query(BotState).all()
    bot_states = []
    for b in bot_states_db:
        anger_dict = json.loads(b.anger_targets)
        eff = calculate_effective_anger(anger_dict)
        bot_states.append({
            "bot_name": b.bot_name,
            "anger_targets": anger_dict,
            "eff_anger": eff
        })
    
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "posts": posts_data, "bot_states": bot_states, "session": latest_session}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run:app", host="0.0.0.0", port=8050, reload=True)
