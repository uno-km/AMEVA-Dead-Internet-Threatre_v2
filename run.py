import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.web.database import init_db
from app.web.router import router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 데이터베이스 초기화 및 기본 테이블/데이터 설정
    init_db()
    yield

app = FastAPI(title="AMEVA-DeadInternetSociety", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")
app.include_router(router)

if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("SERVER_PORT", "8050"))
    reload_enabled = os.getenv("APP_RELOAD", "true").lower() == "true"
    print(f"[System] 웹 서버를 구동합니다: http://{host}:{port} (Reload: {reload_enabled})")
    uvicorn.run("run:app", host=host, port=port, reload=reload_enabled)
