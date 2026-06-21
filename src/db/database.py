import os
import logging
from sqlalchemy import create_engine, event, text
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
    try:
        # Docker on Windows bind mounts often fail with WAL mode due to shared memory lock issues.
        # We will use the default journal_mode (DELETE) to avoid disk I/O errors natively.
        # cursor.execute("PRAGMA journal_mode=WAL")  <- Removed to prevent disk I/O error
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
    except Exception as e:
        logger.warning(f"Could not set SQLite PRAGMA: {e}")
    finally:
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    """앱 기동 시 최초 1회 실행되는 DB 초기화 로직"""
    from src.db.models import BotState, Board, Session, CurrentAgentState
    import json
    
    # 메타데이터 기반 테이블 자동 생성
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if current_activity column exists in active_nodes, if not, add it
        try:
            db.execute(text("ALTER TABLE active_nodes ADD COLUMN current_activity VARCHAR DEFAULT 'Idle'"))
            db.commit()
            logger.info("[DB] Added current_activity column to active_nodes table.")
        except Exception:
            # Ignore if column already exists
            db.rollback()

        # Load personas from personas.json if it exists
        personas = {}
        try:
            with open("personas.json", "r", encoding="utf-8") as f:
                personas = json.load(f)
        except Exception as pe:
            logger.warning(f"Could not load personas.json: {pe}")

        bots = ["bot_1", "bot_2", "bot_3"]
        
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
        db.close() # 세션 반환은 선택이 아닌 필수입니다.

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
