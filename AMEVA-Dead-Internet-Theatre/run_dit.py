import os
import uvicorn
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.web.database import init_db
from app.web.router import router
from app.services.event_bus import init_event_bus
from app.services.consumers import ActionProcessorConsumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DITRunner")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. DB 초기화
    init_db()
    # 2. 이벤트 버스 초기화
    init_event_bus()
    
    # 3. 백그라운드 Action Processor Consumer 기동
    tasks = []
    exp_ids_str = os.getenv("EXPERIMENT_IDS", "EXP_TEST,EXP_DIT")
    exp_ids = [eid.strip() for eid in exp_ids_str.split(",") if eid.strip()]
    
    for exp_id in exp_ids:
        processor = ActionProcessorConsumer(exp_id)
        tasks.append(asyncio.create_task(processor.start_loop()))
        
    logger.info(f"Started Action Processor Consumers for experiments: {exp_ids}")
    
    if os.getenv("START_SIMULATION", "false").lower() == "true":
        from app.services.state_manager import state_manager, SystemState
        state_manager.set_state(SystemState.PAUSED)
        from app.services.runner import run_session
        sim_task = asyncio.create_task(run_session())
        tasks.append(sim_task)
        logger.info("Started Simulation Runner inside DIT server lifespan.")
        
    # 플랫폼 연동용 WebSocket 브리지 구동
    from app.services.platform_bridge import PlatformBridge
    bridge = PlatformBridge("EXP_TEST")
    bridge_task = asyncio.create_task(bridge.start_loop())
    tasks.append(bridge_task)
    logger.info("Started Platform Websocket Bridge in lifespan.")
    
    yield
    
    # 4. 백그라운드 소비자 종료
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Stopped all Action Processor Consumers")

app = FastAPI(title="AMEVA-Dead-Internet-Theatre", lifespan=lifespan)
base_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(base_dir, "app", "ui", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.include_router(router)


if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("DIT_PORT", os.getenv("SERVER_PORT", "8080"))) # 포트는 플랫폼 허브와 다르게 8080을 디폴트로 사용
    reload_enabled = os.getenv("APP_RELOAD", "false").lower() == "true"
    logger.info(f"[System] DIT Experiment Server starting at http://{host}:{port}")
    uvicorn.run("run_dit:app", host=host, port=port, reload=reload_enabled)
