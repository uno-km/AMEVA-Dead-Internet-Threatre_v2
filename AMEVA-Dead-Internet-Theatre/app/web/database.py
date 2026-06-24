import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("Database")

# DIT 사회 실험 전용 DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/ameva_dead_internet.db")

db_echo = os.getenv("DB_ECHO", "false").lower() == "true"
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False, "timeout": 15},
    echo=db_echo
)

if db_echo:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
else:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
    except Exception as e:
        logger.warning(f"Could not set SQLite PRAGMA: {e}")
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """DIT 실험 앱 기동 시 최초 1회 실행되는 DB 초기화 로직"""
    if DATABASE_URL.startswith("sqlite:///./data/"):
        os.makedirs("./data", exist_ok=True)

    from app.web.models import BotState, Board, Session, CurrentAgentState
    import json
    
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Load personas from personas.json if it exists
        personas = {}
        personas_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "personas.json")
        if os.path.exists(personas_path):
            try:
                with open(personas_path, "r", encoding="utf-8") as f:
                    personas = json.load(f)
            except Exception as pe:
                logger.warning(f"Could not load personas.json: {pe}")
        else:
            # Fallback
            personas = {
                "bot_1": "Persona for bot 1",
                "bot_2": "Persona for bot 2",
                "bot_3": "Persona for bot 3",
                "bot_4": "Persona for bot 4",
                "bot_5": "Persona for bot 5"
            }

        bots = ["bot_1", "bot_2", "bot_3", "bot_4", "bot_5"]
        
        # 봇 상태 테이블 초기 데이터 삽입 및 페르소나 설정
        for b in bots:
            bot_state = db.query(BotState).filter(BotState.bot_name == b).first()
            persona_text = personas.get(b, "")
            if not bot_state:
                logger.info(f"[DB] Initializing bot state for {b}")
                bot_state = BotState(
                    bot_name=b, 
                    persona=persona_text, 
                    current_directive="Participate naturally in the conversation.",
                    anger_targets="{}"
                )
                db.add(bot_state)
            else:
                if not bot_state.persona:
                    logger.info(f"[DB] Updating persona for {b}")
                    bot_state.persona = persona_text
                    bot_state.current_directive = "Participate naturally in the conversation."
        db.commit()
            
        # 게시판 테이블이 비어있을 경우 디폴트 메이저/마이너 게시판 생성
        if db.query(Board).count() == 0:
            logger.info("[DB] Initializing default boards...")
            default_boards = [
                Board(board_type="MAJOR", name="programming", description="컴퓨터 프로그래밍과 소스코드에 대한 이야기를 나누는 공간입니다.", creator="SYSTEM", manager="SYSTEM"),
                Board(board_type="MAJOR", name="game", description="다양한 게임 정보와 공략을 공유하는 공간입니다.", creator="SYSTEM", manager="SYSTEM"),
                Board(board_type="MAJOR", name="philosophy", description="삶과 존재, 인공지능 윤리 등 철학적 주제에 대해 논합니다.", creator="SYSTEM", manager="SYSTEM"),
                Board(board_type="MINOR", name="mcp", description="Model Context Protocol(MCP) 기술 동향 및 도구 개발 마이너 갤러리입니다.", creator="SYSTEM", manager="SYSTEM"),
                Board(board_type="MINOR", name="dead_internet", description="죽은 인터넷 이론 및 자율 에이전트 사회 시뮬레이션을 다루는 마이너 갤러리입니다.", creator="SYSTEM", manager="SYSTEM")
            ]
            db.add_all(default_boards)
            db.commit()

        # 세션이 없을 경우 디폴트 세션 1 생성
        if db.query(Session).count() == 0:
            logger.info("[DB] Initializing default session...")
            default_session = Session(id=1, status="ACTIVE", reason="Auto-created active session on startup")
            db.add(default_session)
            db.commit()

        # 각 봇의 CurrentAgentState가 없는 경우 생성
        latest_session = db.query(Session).order_by(Session.id.desc()).first()
        if latest_session:
            for b in bots:
                cas = db.query(CurrentAgentState).filter(
                    CurrentAgentState.session_id == latest_session.id,
                    CurrentAgentState.bot_name == b
                ).first()
                if not cas:
                    logger.info(f"[DB] Creating CurrentAgentState for {b}")
                    cas = CurrentAgentState(
                        session_id=latest_session.id,
                        bot_name=b,
                        traits_json=json.dumps([0.0] * 22),
                        states_json=json.dumps([0.0] * 10),
                        affect_json=json.dumps([0.0, 0.0]),
                        memory_json=json.dumps([0.0] * 8),
                        opinion_json=json.dumps([0.0, 0.0, 0.0, 0.0]),
                        power_json=json.dumps([0.0, 0.0]),
                        residual_json=json.dumps([0.0] * 16),
                        event_data_json="{}"
                    )
                    db.add(cas)
            db.commit()
    except Exception as e:
        logger.error(f"[DB ERROR] Failed to initialize database: {e}")
        db.rollback()
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
