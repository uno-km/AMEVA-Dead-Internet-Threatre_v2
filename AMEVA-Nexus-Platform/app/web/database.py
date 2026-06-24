import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("Database")

# 플랫폼 코어 DB
DATABASE_URL = os.getenv("PLATFORM_DATABASE_URL", os.getenv("DATABASE_URL", "sqlite:///./data/ameva_core.db"))

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
    """플랫폼 코어 앱 기동 시 최초 1회 실행되는 DB 초기화 로직"""
    if DATABASE_URL.startswith("sqlite:///./data/"):
        os.makedirs("./data", exist_ok=True)

    from app.web.models import Account, Transfer, LedgerEntry, Reputation, ExperimentSpec, WorkerNode, DispatchAssignment, AuditEvent, ActiveNode, ArchivePost, ArchiveComment, ArchiveAgentStateSnapshot, Wallet, TokenTransaction
    
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Check if current_activity column exists in active_nodes, if not, add it
        try:
            db.execute(text("ALTER TABLE active_nodes ADD COLUMN current_activity VARCHAR DEFAULT 'Idle'"))
            db.commit()
            logger.info("[DB] Added current_activity column to active_nodes table.")
        except Exception:
            db.rollback()

        # SYSTEM_REWARD_POOL 계정이 없으면 초기화 생성
        sys_account = db.query(Account).filter(Account.entity_name == "SYSTEM_REWARD_POOL").first()
        if not sys_account:
            logger.info("[DB] Creating SYSTEM_REWARD_POOL account with 1000000.0 balance.")
            sys_account = Account(
                entity_name="SYSTEM_REWARD_POOL",
                account_type="EXPENSE",
                balance=1000000.0
            )
            db.add(sys_account)
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
