from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.web.database import Base

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True, index=True)
    entity_name = Column(String, unique=True, index=True, nullable=False) # 'bot_1', 'SYSTEM_REWARD_POOL'
    account_type = Column(String, default="ASSET") # ASSET, LIABILITY, REVENUE, EXPENSE
    balance = Column(Float, default=0.0) # Cached balance
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class Transfer(Base):
    __tablename__ = 'transfers'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, nullable=True, index=True)
    transfer_type = Column(String, nullable=False) # 'REWARD', 'POST_TAX', 'WITHDRAWAL'
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    entries = relationship("LedgerEntry", back_populates="transfer")

class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'
    id = Column(Integer, primary_key=True, index=True)
    transfer_id = Column(Integer, ForeignKey('transfers.id'), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    entry_direction = Column(String, nullable=False) # 'DEBIT', 'CREDIT'
    created_at = Column(DateTime, default=datetime.now)

    transfer = relationship("Transfer", back_populates="entries")
    account = relationship("Account")

class Reputation(Base):
    __tablename__ = 'reputations'
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, unique=True, index=True, nullable=False)
    success_rate = Column(Float, default=1.0)
    avg_latency = Column(Float, default=0.0)
    offline_count = Column(Integer, default=0)
    score = Column(Float, default=100.0)
    capability_score = Column(Float, default=100.0)
    reliability_score = Column(Float, default=100.0)
    quality_score = Column(Float, default=100.0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class ExperimentSpec(Base):
    __tablename__ = 'experiment_specs'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, unique=True, index=True, nullable=False)
    min_vram_gb = Column(Float, default=0.0)
    required_model = Column(String, nullable=True)
    status = Column(String, default="REGISTERED") # REGISTERED, RECRUITING, RUNNING, CLOSED
    max_participants = Column(Integer, default=5)
    recruitment_start_time = Column(DateTime, nullable=True)
    actual_start_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class WorkerNode(Base):
    __tablename__ = 'worker_nodes'
    node_id = Column(String, primary_key=True)
    cpu_info = Column(String, nullable=True)
    ram_gb = Column(Float, default=0.0)
    gpu_model = Column(String, nullable=True)
    vram_gb = Column(Float, default=0.0)
    available_models_json = Column(Text, default="[]")
    last_benchmarked_at = Column(DateTime, nullable=True)
    is_verified = Column(Integer, default=0)  # 0: Unverified, 1: Verified
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class DispatchAssignment(Base):
    __tablename__ = 'dispatch_assignments'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, index=True, nullable=False)
    node_id = Column(String, ForeignKey('worker_nodes.node_id'), nullable=False, index=True)
    agent_id = Column(String, index=True, nullable=False)
    status = Column(String, default="ASSIGNED") # ASSIGNED, RELEASED
    assigned_at = Column(DateTime, default=datetime.now)


class Wallet(Base):
    __tablename__ = 'wallets'
    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, nullable=False)
    entity_name = Column(String, unique=True, index=True, nullable=False)
    wallet_address = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class TokenTransaction(Base):
    __tablename__ = 'token_transactions'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, nullable=True, index=True)
    sender_wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=True, index=True)
    receiver_wallet_id = Column(Integer, ForeignKey('wallets.id'), nullable=True, index=True)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    sender = relationship("Wallet", foreign_keys=[sender_wallet_id])
    receiver = relationship("Wallet", foreign_keys=[receiver_wallet_id])

class ActiveNode(Base):
    __tablename__ = 'active_nodes'

    node_id = Column(String, primary_key=True)
    bot_name = Column(String, index=True)
    status = Column(String, default="ACTIVE")
    hardware_mode = Column(String, default="CPU")
    current_activity = Column(String, default="Idle")
    last_seen = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, index=True)
    tenant_id = Column(String, index=True)
    experiment_id = Column(String, index=True)
    agent_id = Column(String, index=True)
    payload_json = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

class FederatedSite(Base):
    __tablename__ = 'federated_sites'
    site_id = Column(String, primary_key=True, index=True)
    site_name = Column(String, nullable=False)
    webhook_url = Column(String, nullable=True)
    status = Column(String, default="ACTIVE") # ACTIVE, SUSPENDED
    created_at = Column(DateTime, default=datetime.now)

class SiteKey(Base):
    __tablename__ = 'site_keys'
    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(String, ForeignKey('federated_sites.site_id'), nullable=False, index=True)
    secret_key = Column(String, nullable=False)
    is_active = Column(Integer, default=1) # 1: Active, 0: Rotated
    created_at = Column(DateTime, default=datetime.now)

class SettlementObligation(Base):
    __tablename__ = 'settlement_obligations'
    obligation_id = Column(String, primary_key=True, index=True)
    experiment_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    status = Column(String, default="PENDING") # PENDING, BATCHED, SETTLED, FAILED
    created_at = Column(DateTime, default=datetime.now)

class SettlementBatch(Base):
    __tablename__ = 'settlement_batches'
    batch_id = Column(String, primary_key=True, index=True)
    experiment_id = Column(String, nullable=False, index=True)
    merkle_root = Column(String, nullable=False)
    status = Column(String, default="OPEN") # OPEN, COMMITTED, SETTLED, FAILED
    created_at = Column(DateTime, default=datetime.now)

class SettlementClaim(Base):
    __tablename__ = 'settlement_claims'
    claim_id = Column(String, primary_key=True, index=True)
    batch_id = Column(String, ForeignKey('settlement_batches.batch_id'), nullable=False, index=True)
    agent_id = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    proof_json = Column(Text, nullable=False) # JSON list of hex hashes
    status = Column(String, default="SUBMITTED") # SUBMITTED, VERIFIED, REJECTED, SETTLED
    created_at = Column(DateTime, default=datetime.now)

# ----------------- 글로벌 아카이브 모델 (데이터 미러링 전용) -----------------

class ArchivePost(Base):
    __tablename__ = 'archive_posts'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, index=True, nullable=False)
    post_id = Column(Integer, index=True, nullable=False)
    board_name = Column(String, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    agent_id = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.now)

class ArchiveComment(Base):
    __tablename__ = 'archive_comments'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, index=True, nullable=False)
    comment_id = Column(Integer, index=True, nullable=False)
    post_id = Column(Integer, index=True, nullable=False)
    parent_id = Column(Integer, nullable=True)
    bot_name = Column(String, index=True)
    content = Column(Text)
    anger_score = Column(Integer, default=0)
    mentioned_bot = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class ArchiveAgentStateSnapshot(Base):
    __tablename__ = 'archive_agent_state_snapshots'
    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(String, index=True, nullable=False)
    session_id = Column(Integer, index=True)
    turn_index = Column(Integer, index=True)
    bot_name = Column(String, index=True)
    traits_json = Column(Text, default="[]")
    states_json = Column(Text, default="[]")
    affect_json = Column(Text, default="[]")
    memory_json = Column(Text, default="[]")
    opinion_json = Column(Text, default="[]")
    power_json = Column(Text, default="[]")
    residual_json = Column(Text, default="[]")
    role_label = Column(String, default="swing_moderate")
    created_at = Column(DateTime, default=datetime.now)
