import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# from src.db.database import init_db
# from src.services.poster import start_poster_loop
# from src.services.commenter import start_commenter_loop
# from src.services.overlord import start_overlord_loop

templates = Jinja2Templates(directory="src/ui/templates")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 앱 시작 및 종료 시 실행할 라이프사이클 관리
    DB 초기화 및 백그라운드 태스크(poster, commenter, overlord) 루프 가동
    """
    # 1. DB 초기화
    # init_db()
    print("[System] Database initialized.")
    
    # 2. 백그라운드 루프(스레드/비동기 태스크) 가동
    # asyncio.create_task(start_poster_loop())
    # asyncio.create_task(start_commenter_loop())
    # asyncio.create_task(start_overlord_loop())
    print("[System] Background tasks (Poster, Commenter, God) started.")
    
    yield
    
    print("[System] Shutting down AMEVA-DeadInternetSociety...")

app = FastAPI(title="AMEVA-DeadInternetSociety", lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """
    메인 게시판 UI 렌더링
    Auto-refresh가 적용된 Jinja2 템플릿 반환
    """
    # 임시 Mock 데이터 (실제는 DB 연동)
    posts = [
        {"id": 1, "title": "첫 번째 글", "content": "LLM 메인 봇이 쓴 첫 번째 글입니다.", "created_at": "2026-06-02 10:00"},
    ]
    comments = {
        1: [
            {"bot_name": "bot_1", "content": "그래봤자 로봇이 쓴 글이네.", "created_at": "2026-06-02 10:01"},
            {"bot_name": "bot_2", "content": "우와 정말 멋진 글이야!", "created_at": "2026-06-02 10:02"}
        ]
    }
    
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "posts": posts, "comments": comments}
    )

# 실행 진입점 (디버깅용)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("run:app", host="0.0.0.0", port=8050, reload=True)
