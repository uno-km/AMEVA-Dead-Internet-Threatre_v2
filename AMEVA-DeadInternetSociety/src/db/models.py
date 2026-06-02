from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="ACTIVE") # ACTIVE, CLOSED
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    posts = relationship("Post", back_populates="session")

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'))
    title = Column(String, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="posts")
    comments = relationship("Comment", back_populates="post")

class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey('posts.id'))
    parent_id = Column(Integer, ForeignKey('comments.id'), nullable=True)
    bot_name = Column(String, index=True)
    content = Column(Text)
    anger_score = Column(Integer, default=0)
    mentioned_bot = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="comments")
    replies = relationship("Comment", back_populates="parent", remote_side=[id])
    parent = relationship("Comment", back_populates="replies", remote_side=[parent_id])

class BotState(Base):
    __tablename__ = 'bot_states'
    bot_name = Column(String, primary_key=True, index=True)
    current_anger = Column(Integer, default=0)
