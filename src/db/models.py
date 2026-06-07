from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from src.db.database import Base

class Session(Base):
    __tablename__ = 'sessions'
    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, default="ACTIVE") # ACTIVE, CLOSED
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    closed_at = Column(DateTime, nullable=True)

    posts = relationship("Post", back_populates="session")

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'))
    title = Column(String, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

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
    created_at = Column(DateTime, default=datetime.now)

    post = relationship("Post", back_populates="comments")
    replies = relationship("Comment", backref="parent", remote_side=[id])

class BotState(Base):
    __tablename__ = 'bot_states'
    id = Column(Integer, primary_key=True, index=True)
    bot_name = Column(String, unique=True, index=True)
    persona = Column(String)
    current_directive = Column(String, nullable=True)
    anger_targets = Column(String, default="{}") # JSON string mapping target bot to anger value
    created_at = Column(DateTime, default=datetime.now)

class SessionBotState(Base):
    __tablename__ = 'session_bot_states'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    persona = Column(String)
    current_directive = Column(String, nullable=True)
    anger_targets = Column(String, default="{}")
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", backref="bot_states")

class CurrentAgentState(Base):
    """현재 LPDE 에이전트 상태 (Shadow Mode)"""
    __tablename__ = 'current_agent_states'
    __table_args__ = (
        UniqueConstraint('session_id', 'bot_name', name='uq_current_agent_state_session_bot'),
    )
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]") # NOTE: Temporary workaround to store event data until event_data_json migration
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AgentStateSnapshot(Base):
    """턴 단위 LPDE 에이전트 상태 로깅"""
    __tablename__ = 'agent_state_snapshots'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]") # NOTE: Temporary workaround to store event data until event_data_json migration
    created_at = Column(DateTime, default=datetime.now)

class EdgeState(Base):
    """방향성 있는 에이전트 간 관계 텐서"""
    __tablename__ = 'edge_states'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    source_bot = Column(String, index=True)
    target_bot = Column(String, index=True)
    relation_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class InterventionLog(Base):
    """God LLM 개입 로그"""
    __tablename__ = 'intervention_logs'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    target_bot = Column(String, index=True)
    kind = Column(String)
    delta_json = Column(Text, default="{}")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
