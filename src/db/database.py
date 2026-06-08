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
