import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base, BotState

DATABASE_URL = "sqlite:///./ameva_society.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Initialize bot states if empty
    db = SessionLocal()
    if db.query(BotState).count() == 0:
        bots = ["bot_1", "bot_2", "bot_3"]
        for b in bots:
            db.add(BotState(bot_name=b, current_anger=0))
        db.commit()
    db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
