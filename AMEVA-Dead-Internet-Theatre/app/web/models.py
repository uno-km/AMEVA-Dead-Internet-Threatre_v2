from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.web.database import Base

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
    id = Column(Integer, primary_key=True, index=True)
    board_id = Column(Integer, ForeignKey('boards.id'), index=True)
    board_seq_id = Column(Integer, default=1)
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

class BotState(Base):
    __tablename__ = 'bot_states'
    id = Column(Integer, primary_key=True, index=True)
    bot_name = Column(String, unique=True, index=True)
    persona = Column(String)
    current_directive = Column(String, nullable=True)
    anger_targets = Column(String, default="{}")
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
    role_label = Column(String, default="swing_moderate")
    role_meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("Session", backref="bot_states")

class CurrentAgentState(Base):
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
    residual_json = Column(Text, default="[]")
    event_data_json = Column(Text, default="{}")
    role_label = Column(String, default="swing_moderate")
    role_meta_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AgentStateSnapshot(Base):
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
    residual_json = Column(Text, default="[]")
    event_data_json = Column(Text, default="{}")
    role_label = Column(String, default="swing_moderate")
    created_at = Column(DateTime, default=datetime.now)

class EdgeState(Base):
    __tablename__ = 'edge_states'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    source_bot = Column(String, index=True)
    target_bot = Column(String, index=True)
    relation_json = Column(Text, default="{}")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class InterventionLog(Base):
    __tablename__ = 'intervention_logs'
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), index=True)
    turn_index = Column(Integer, index=True)
    target_bot = Column(String, index=True)
    kind = Column(String)
    delta_json = Column(Text, default="{}")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

# ----------------- 통합 테스트 및 임포트 충돌 방지용 임시 스텁 모델 -----------------
class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)
    entity_name = Column(String)
    balance = Column(Float)

class Transfer(Base):
    __tablename__ = 'transfers'
    id = Column(Integer, primary_key=True)
    transfer_type = Column(String)

class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'
    id = Column(Integer, primary_key=True)

class Reputation(Base):
    __tablename__ = 'reputations'
    id = Column(Integer, primary_key=True)
    agent_id = Column(String)
    success_rate = Column(Float)
    avg_latency = Column(Float)
    offline_count = Column(Integer)
    score = Column(Float)
    capability_score = Column(Float)
    reliability_score = Column(Float)
    quality_score = Column(Float)

class Wallet(Base):
    __tablename__ = 'wallets'
    id = Column(Integer, primary_key=True)
    entity_name = Column(String)
    balance = Column(Float)

class TokenTransaction(Base):
    __tablename__ = 'token_transactions'
    id = Column(Integer, primary_key=True)

class FederatedSite(Base):
    __tablename__ = 'federated_sites'
    site_id = Column(String, primary_key=True)
    site_name = Column(String)
    webhook_url = Column(String)
    status = Column(String)

class SiteKey(Base):
    __tablename__ = 'site_keys'
    id = Column(Integer, primary_key=True)
    site_id = Column(String)
    secret_key = Column(String)
    is_active = Column(Integer)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id = Column(Integer, primary_key=True)
    event_type = Column(String)
    tenant_id = Column(String)
    experiment_id = Column(String)
    agent_id = Column(String)
    payload_json = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

class SettlementObligation(Base):
    __tablename__ = 'settlement_obligations'
    obligation_id = Column(String, primary_key=True)
    experiment_id = Column(String)
    agent_id = Column(String)
    amount = Column(Float)
    status = Column(String)

class SettlementBatch(Base):
    __tablename__ = 'settlement_batches'
    batch_id = Column(String, primary_key=True)
    experiment_id = Column(String)
    merkle_root = Column(String)
    status = Column(String)

class SettlementClaim(Base):
    __tablename__ = 'settlement_claims'
    claim_id = Column(String, primary_key=True)
    batch_id = Column(String)
    agent_id = Column(String)
    amount = Column(Float)
    proof_json = Column(Text)
    status = Column(String)

class WorkerNode(Base):
    __tablename__ = 'worker_nodes'
    node_id = Column(String, primary_key=True)
    cpu_info = Column(String)
    ram_gb = Column(Float)
    gpu_model = Column(String)
    vram_gb = Column(Float)
    available_models_json = Column(Text)
    last_benchmarked_at = Column(DateTime)
    is_verified = Column(Integer)

class ArchivePost(Base):
    __tablename__ = 'archive_posts'
    id = Column(Integer, primary_key=True)
    experiment_id = Column(String)
    post_id = Column(Integer)
    board_name = Column(String)
    title = Column(String)
    content = Column(Text)
    agent_id = Column(String)
    created_at = Column(DateTime)

class ArchiveComment(Base):
    __tablename__ = 'archive_comments'
    id = Column(Integer, primary_key=True)
    experiment_id = Column(String)
    comment_id = Column(Integer)
    post_id = Column(Integer)
    parent_id = Column(Integer)
    bot_name = Column(String)
    content = Column(Text)
    anger_score = Column(Integer)
    mentioned_bot = Column(String)
    created_at = Column(DateTime)

class ActiveNode(Base):
    __tablename__ = 'active_nodes'
    node_id = Column(String, primary_key=True)
    bot_name = Column(String)
    status = Column(String)
    hardware_mode = Column(String)
    current_activity = Column(String)
    last_seen = Column(DateTime)

class ExperimentSpec(Base):
    __tablename__ = 'experiment_specs'
    id = Column(Integer, primary_key=True)
    experiment_id = Column(String)
    min_vram_gb = Column(Float)
    required_model = Column(String)

class DispatchAssignment(Base):
    __tablename__ = 'dispatch_assignments'
    id = Column(Integer, primary_key=True)
    experiment_id = Column(String)
    node_id = Column(String)
    agent_id = Column(String)
    status = Column(String)





