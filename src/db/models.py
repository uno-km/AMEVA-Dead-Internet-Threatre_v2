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

class Board(Base):
    __tablename__ = 'boards'
    id = Column(Integer, primary_key=True, index=True)
    board_type = Column(String, default="MAJOR")  # MAJOR, MINOR
    name = Column(String, unique=True, index=True)
    description = Column(Text, nullable=True)
    creator = Column(String, default="SYSTEM")
    manager = Column(String, default="SYSTEM")
    created_at = Column(DateTime, default=datetime.now)

    posts = relationship("Post", back_populates="board")

class Post(Base):
    __tablename__ = 'posts'
    id = Column(Integer, primary_key=True, index=True)  # 전체글 순차 ID
    board_id = Column(Integer, ForeignKey('boards.id'), index=True)
    board_seq_id = Column(Integer, default=1)  # 특정 게시판 내 순차 ID
    session_id = Column(Integer, ForeignKey('sessions.id'), nullable=True)
    title = Column(String, index=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    board = relationship("Board", back_populates="posts")
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

class ActiveNode(Base):
    __tablename__ = 'active_nodes'
    node_id = Column(String, primary_key=True)
    bot_name = Column(String, index=True)
    status = Column(String, default="ACTIVE")
    hardware_mode = Column(String, default="CPU")  # CPU or GPU
    current_activity = Column(String, default="Idle")
    last_seen = Column(DateTime, default=datetime.now, onupdate=datetime.now)

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
    role_label = Column(String, default="swing_moderate")   # Phase 3: stance role label (restart 복원용)
    role_meta_json = Column(Text, default="{}")             # Phase 3: full role profile (restart 복원용)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", backref="bot_states")

class CurrentAgentState(Base):
    """
    현재 LPDE 에이전트 상태 (Phase 2 Shadow Mode + Phase 3 Stance Role)

    opinion_json 차원 정의 (Phase 3 재정의):
      opinion[0] = stance_pole     : 논쟁 축 방향 [-1.0 ~ +1.0]
      opinion[1] = conviction      : 자기 입장 확신도 [0.0 ~ 1.0]
      opinion[2] = moral_salience  : 도덕적 민감도 [0.0 ~ 1.0] (기존 유지)
      opinion[3] = flexibility     : 반박 시 흔들림 정도 [0.0 ~ 1.0]
    """
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
    opinion_json = Column(Text, default="[]")   # [stance_pole, conviction, moral_salience, flexibility]
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]")
    event_data_json = Column(Text, default="{}")        # Phase 2 Event storage
    role_label = Column(String, default="swing_moderate")   # Phase 3: stance role label
    role_meta_json = Column(Text, default="{}")             # Phase 3: full role profile (opportunism, aggression_bias, etc.)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AgentStateSnapshot(Base):
    """
    턴 단위 LPDE 에이전트 상태 로깅 (Phase 3: role 포함)

    opinion_json 차원 정의 (Phase 3 재정의):
      opinion[0] = stance_pole     : 논쟁 축 방향 [-1.0 ~ +1.0]
      opinion[1] = conviction      : 자기 입장 확신도 [0.0 ~ 1.0]
      opinion[2] = moral_salience  : 도덕적 민감도 [0.0 ~ 1.0] (기존 유지)
      opinion[3] = flexibility     : 반박 시 흔들림 정도 [0.0 ~ 1.0]
    """
    __tablename__ = 'agent_state_snapshots'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")   # [stance_pole, conviction, moral_salience, flexibility]
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]")
    event_data_json = Column(Text, default="{}")    # Phase 2 Event storage
    role_label = Column(String, default="swing_moderate")  # Phase 3: snapshot 시점의 role label
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
