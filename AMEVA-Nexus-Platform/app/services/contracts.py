from pydantic import BaseModel, Field
from datetime import datetime
from typing import Dict, Any, List, Optional

class FederationEventEnvelope(BaseModel):
    schema_version: str = Field(..., example="1.0.0")
    site_id: str
    experiment_id: str
    event_id: str
    occurred_at: str  # ISO 8601 string
    event_type: str
    payload: Dict[str, Any]
    extensions: Dict[str, Any] = Field(default_factory=dict)

class DispatchRequest(BaseModel):
    experiment_id: str
    min_vram_gb: float
    required_model: str
    assigned_at: datetime = Field(default_factory=datetime.now)

class DispatchAck(BaseModel):
    experiment_id: str
    node_id: str
    status: str = "ASSIGNED"
    accepted: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)

class ExperimentStatusUpdate(BaseModel):
    experiment_id: str
    status: str  # RUNNING, CLOSED, FAILED
    updated_at: datetime = Field(default_factory=datetime.now)
    details: Optional[str] = None

class ExperimentSummary(BaseModel):
    experiment_id: str
    total_posts: int
    total_comments: int
    total_accrued_reward: float
    total_charged_fee: float
    last_event_id: Optional[str] = None
    checksum: Optional[str] = None

class RewardAccrualReport(BaseModel):
    experiment_id: str
    agent_id: str
    amount: float
    transaction_type: str  # REWARD, POST_TAX
    description: str
    timestamp: datetime = Field(default_factory=datetime.now)

class ReconciliationCursorResponse(BaseModel):
    site_id: str
    last_processed_timestamp: float
    events: List[Dict[str, Any]]
    has_more: bool
    next_cursor: Optional[str] = None

class ErrorContract(BaseModel):
    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)
