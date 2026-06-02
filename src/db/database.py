import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("Database")

DATABASE_URL =  "sqlite:///./data/ameva_society.db"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False, "timeout": 15}
)

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
