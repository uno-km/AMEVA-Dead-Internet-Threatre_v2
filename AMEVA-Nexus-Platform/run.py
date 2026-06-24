import os
import uvicorn
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from app.services.security import verify_signature
from app.services.contracts import ExperimentSummary

from app.web.database import init_db, get_db
from app.web.websocket_router import router as ws_router
from app.services.event_bus import init_event_bus
from app.services.settlement import SettlementService
from app.services.consumers import FanoutNotifierConsumer, PresenceMonitor
from app.services.archiver import ResearchArchiverConsumer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PlatformCore")

# 정산 및 Control Plane API 스키마
class SiteRegisterRequest(BaseModel):
    site_id: str
    site_name: str
    webhook_url: str = None

class AccrueRewardRequest(BaseModel):
    experiment_id: str
    agent_id: str
    amount: float
    description: str

class ChargeFeeRequest(BaseModel):
    experiment_id: str
    entity_name: str
    amount: float
    fee_type: str
    description: str

class WorkerRegisterRequest(BaseModel):
    node_id: str
    cpu_info: str
    ram_gb: float
    gpu_model: str
    vram_gb: float
    available_models: list[str]

class ExperimentSpecRegisterRequest(BaseModel):
    experiment_id: str
    min_vram_gb: float
    required_model: str

class DispatchRequest(BaseModel):
    experiment_id: str
    max_participants: int = 5

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. DB 초기화
    init_db()
    # 2. 이벤트 버스 초기화
    init_event_bus()
    
    # 3. 백그라운드 소비자 기동
    tasks = []
    
    # Presence Monitor
    monitor = PresenceMonitor()
    tasks.append(asyncio.create_task(monitor.start_loop()))
    
    # 감청할 실험 ID 목록
    exp_ids_str = os.getenv("EXPERIMENT_IDS", "EXP_TEST,EXP_DIT")
    exp_ids = [eid.strip() for eid in exp_ids_str.split(",") if eid.strip()]
    
    for exp_id in exp_ids:
        # Fanout Notifier
        notifier = FanoutNotifierConsumer(exp_id)
        tasks.append(asyncio.create_task(notifier.start_loop()))
        
        # Research Archiver
        archiver = ResearchArchiverConsumer(exp_id)
        tasks.append(asyncio.create_task(archiver.start_loop()))
        
    logger.info(f"Started background services for experiments: {exp_ids}")
    
    yield
    
    # 4. 백그라운드 서비스 종료
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Stopped all background services")

app = FastAPI(title="AMEVA-Nexus-Platform", lifespan=lifespan)
app.include_router(ws_router)

# ----------------- 정산 및 복식 부기 원장 API -----------------

@app.post("/api/v1/settlement/accrue")
def accrue_reward_api(req: AccrueRewardRequest, db: Session = Depends(get_db)):
    from app.web.models import Account, Wallet
    try:
        tx = SettlementService.accrue_reward(
            db=db,
            experiment_id=req.experiment_id,
            agent_id=req.agent_id,
            amount=req.amount,
            description=req.description
        )
        agent_acc = db.query(Account).filter_by(entity_name=req.agent_id).first()
        
        # 하위 호환을 위한 Wallet balance 동기화
        wallet = db.query(Wallet).filter_by(entity_name=req.agent_id).first()
        if wallet and agent_acc:
            wallet.balance = agent_acc.balance
            db.commit()
            
        return {
            "status": "success",
            "transaction_id": tx.id,
            "amount": tx.entries[0].amount if tx.entries else req.amount,
            "balance": agent_acc.balance if agent_acc else 0.0
        }
    except Exception as e:
        logger.error(f"Accrue reward API failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/settlement/charge")
def charge_fee_api(req: ChargeFeeRequest, db: Session = Depends(get_db)):
    from app.web.models import Account, Wallet
    try:
        tx = SettlementService.charge_fee(
            db=db,
            experiment_id=req.experiment_id,
            entity_name=req.entity_name,
            amount=req.amount,
            fee_type=req.fee_type,
            description=req.description
        )
        agent_acc = db.query(Account).filter_by(entity_name=req.entity_name).first()
        
        # 하위 호환을 위한 Wallet balance 동기화
        wallet = db.query(Wallet).filter_by(entity_name=req.entity_name).first()
        if wallet and agent_acc:
            wallet.balance = agent_acc.balance
            db.commit()
            
        return {
            "status": "success",
            "transaction_id": tx.id,
            "amount": tx.entries[0].amount if tx.entries else req.amount,
            "balance": agent_acc.balance if agent_acc else 0.0
        }
    except Exception as e:
        logger.error(f"Charge fee API failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/settlement/wallets/{entity_name}")
def get_wallet_api(entity_name: str, db: Session = Depends(get_db)):
    # 하위 호환성 유지: Wallet 대신 Account 조회하여 balance 응답
    account = SettlementService.get_or_create_account(db, entity_name, "ASSET")
    return {
        "entity_name": account.entity_name,
        "entity_type": "AGENT" if account.entity_name != "SYSTEM_REWARD_POOL" else "RESEARCHER",
        "balance": account.balance,
        "wallet_address": None
    }

# ----------------- Control Plane & 디스패치 & 평판 API -----------------

@app.get("/api/v1/reputations/{agent_id}")
def get_reputation_api(agent_id: str, db: Session = Depends(get_db)):
    from app.web.models import Reputation
    rep = db.query(Reputation).filter_by(agent_id=agent_id).first()
    if not rep:
        # 최초 요청 시 기본 평판 생성
        rep = Reputation(agent_id=agent_id, score=100.0)
        db.add(rep)
        db.commit()
        db.refresh(rep)
    return {
        "agent_id": rep.agent_id,
        "success_rate": rep.success_rate,
        "avg_latency": rep.avg_latency,
        "offline_count": rep.offline_count,
        "score": rep.score
    }

@app.post("/api/v1/workers/register")
def register_worker_api(req: WorkerRegisterRequest, db: Session = Depends(get_db)):
    from app.web.models import WorkerNode, ActiveNode
    import json
    from datetime import datetime
    node = db.query(WorkerNode).filter_by(node_id=req.node_id).first()
    if not node:
        node = WorkerNode(
            node_id=req.node_id,
            cpu_info=req.cpu_info,
            ram_gb=req.ram_gb,
            gpu_model=req.gpu_model,
            vram_gb=req.vram_gb,
            available_models_json=json.dumps(req.available_models)
        )
        db.add(node)
    else:
        node.cpu_info = req.cpu_info
        node.ram_gb = req.ram_gb
        node.gpu_model = req.gpu_model
        node.vram_gb = req.vram_gb
        node.available_models_json = json.dumps(req.available_models)
    
    # 워커 등록 시 자동으로 활성 노드(ActiveNode)로 등록/갱신
    from app.web.models import ExperimentSpec, DispatchAssignment
    is_assigned_active = False
    assignments = db.query(DispatchAssignment).filter_by(node_id=req.node_id, status="ASSIGNED").all()
    for assign in assignments:
        spec = db.query(ExperimentSpec).filter_by(experiment_id=assign.experiment_id).first()
        if spec and spec.status == "RUNNING":
            is_assigned_active = True
            break
            
    status_val = "ACTIVE" if is_assigned_active else "LOBBY_WAITING"
    activity_val = "Registered" if is_assigned_active else "LOBBY Waiting"

    active = db.query(ActiveNode).filter_by(node_id=f"node_{req.node_id}").first()
    if not active:
        active = ActiveNode(
            node_id=f"node_{req.node_id}",
            bot_name=f"bot_{req.node_id}",
            status=status_val,
            hardware_mode="GPU" if req.vram_gb > 0 else "CPU",
            current_activity=activity_val,
            last_seen=datetime.now()
        )
        db.add(active)
    else:
        active.status = status_val
        active.hardware_mode = "GPU" if req.vram_gb > 0 else "CPU"
        active.current_activity = activity_val
        active.last_seen = datetime.now()

    db.commit()

    # 벤치마크 자동 수행 (Anti-Sybil 검증)
    from app.services.benchmark_probe import CapabilityProbeService
    try:
        CapabilityProbeService.run_benchmark(db, req.node_id)
    except Exception as e:
        logger.error(f"Auto benchmark failed for node '{req.node_id}': {e}")

    return {"status": "success", "node_id": req.node_id}

@app.post("/api/v1/experiments/register")
def register_experiment_api(req: ExperimentSpecRegisterRequest, db: Session = Depends(get_db)):
    from app.web.models import ExperimentSpec
    spec = db.query(ExperimentSpec).filter_by(experiment_id=req.experiment_id).first()
    if not spec:
        spec = ExperimentSpec(
            experiment_id=req.experiment_id,
            min_vram_gb=req.min_vram_gb,
            required_model=req.required_model
        )
        db.add(spec)
    else:
        spec.min_vram_gb = req.min_vram_gb
        spec.required_model = req.required_model
    db.commit()
    return {"status": "success", "experiment_id": req.experiment_id}

@app.post("/api/v1/dispatcher/dispatch")
def dispatch_api(req: DispatchRequest, db: Session = Depends(get_db)):
    from app.services.dispatcher_service import DispatcherService
    from app.services.observability import metrics
    try:
        res = DispatcherService.start_recruitment(db, req.experiment_id, req.max_participants)
        metrics.increment("dispatch_success_total", labels={"experiment_id": req.experiment_id})
        return {
            "status": "success",
            "experiment_id": req.experiment_id,
            "recruitment_status": res["status"],
            "assigned_count": res["assigned_count"],
            "assigned_workers": res["assigned_workers"]
        }
    except ValueError as e:
        metrics.increment("dispatch_failure_total", labels={"experiment_id": req.experiment_id})
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        metrics.increment("dispatch_failure_total", labels={"experiment_id": req.experiment_id})
        logger.error(f"Dispatch failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/v1/dispatcher/recruitment/status/{experiment_id}")
def check_recruitment_status_api(experiment_id: str, db: Session = Depends(get_db)):
    from app.services.dispatcher_service import DispatcherService
    try:
        res = DispatcherService.check_recruitment_status(db, experiment_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

from fastapi import Response

@app.get("/metrics")
def get_metrics_api():
    from app.services.observability import metrics
    return Response(content=metrics.generate_prometheus_format(), media_type="text/plain")

@app.post("/api/v1/sre/chaos")
def configure_chaos_api(req: dict):
    from app.services.chaos_injector import chaos_injector
    chaos_injector.configure(req)
    return {"status": "success", "config": req}

@app.post("/api/v1/sre/replay")
def trigger_replay_api(req: dict, db: Session = Depends(get_db)):
    from app.services.replay_service import ReplayEngine
    experiment_id = req.get("experiment_id")
    if not experiment_id:
        raise HTTPException(status_code=400, detail="experiment_id is required")
    try:
        success = ReplayEngine.replay_experiment(db, experiment_id)
        return {"status": "success" if success else "failed", "experiment_id": experiment_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/sre/benchmark/trigger")
def trigger_benchmark_api(req: dict, db: Session = Depends(get_db)):
    from app.services.benchmark_probe import CapabilityProbeService
    node_id = req.get("node_id")
    if not node_id:
        raise HTTPException(status_code=400, detail="node_id is required")
    try:
        result = CapabilityProbeService.run_benchmark(db, node_id)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ----------------- 다기관 연합 (Federation) API -----------------

@app.post("/api/v1/federation/sites/register")
def register_federated_site_api(req: SiteRegisterRequest, db: Session = Depends(get_db)):
    from app.web.models import FederatedSite, SiteKey
    import secrets

    # 중복 체크
    exists = db.query(FederatedSite).filter_by(site_id=req.site_id).first()
    if exists:
        raise HTTPException(status_code=400, detail="Site ID already registered")

    site = FederatedSite(
        site_id=req.site_id,
        site_name=req.site_name,
        webhook_url=req.webhook_url,
        status="ACTIVE"
    )
    db.add(site)

    # HMAC 비밀키 생성
    secret_key = secrets.token_hex(32)
    site_key = SiteKey(
        site_id=req.site_id,
        secret_key=secret_key,
        is_active=1
    )
    db.add(site_key)
    db.commit()

    return {
        "status": "success",
        "site_id": site.site_id,
        "secret_key": secret_key
    }

@app.get("/api/v1/federation/reconciliation/events")
def get_reconciliation_events_api(
    since_timestamp: float = 0.0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    from app.web.models import AuditEvent
    from datetime import datetime
    import json

    dt = datetime.fromtimestamp(since_timestamp)
    events = db.query(AuditEvent).filter(AuditEvent.created_at >= dt).order_by(AuditEvent.id.asc()).limit(limit).all()

    event_list = []
    for e in events:
        try:
            payload = json.loads(e.payload_json) if e.payload_json else {}
        except Exception:
            payload = {}

        event_list.append({
            "schema_version": "1.0.0",
            "site_id": e.tenant_id,
            "experiment_id": e.experiment_id,
            "event_id": f"evt_audit_{e.id}",
            "occurred_at": e.created_at.isoformat(),
            "event_type": e.event_type,
            "payload": payload,
            "extensions": {}
        })

    return {
        "events": event_list,
        "has_more": len(events) == limit,
        "next_cursor_timestamp": events[-1].created_at.timestamp() if events else since_timestamp
    }

@app.post("/api/v1/federation/reconciliation/verify")
def verify_reconciliation_summary_api(req: ExperimentSummary, db: Session = Depends(get_db)):
    from app.web.models import Transfer, LedgerEntry
    from sqlalchemy import func

    # REWARD (Accrued Reward) 총합
    accrued = db.query(func.sum(LedgerEntry.amount)).\
        join(Transfer, Transfer.id == LedgerEntry.transfer_id).\
        filter(Transfer.experiment_id == req.experiment_id).\
        filter(Transfer.transfer_type == "REWARD").\
        filter(LedgerEntry.entry_direction == "DEBIT").scalar() or 0.0

    # POST_TAX (FEE) 총합
    charged = db.query(func.sum(LedgerEntry.amount)).\
        join(Transfer, Transfer.id == LedgerEntry.transfer_id).\
        filter(Transfer.experiment_id == req.experiment_id).\
        filter(Transfer.transfer_type != "REWARD").\
        filter(LedgerEntry.entry_direction == "CREDIT").scalar() or 0.0

    mismatch = False
    details = []

    if abs(accrued - req.total_accrued_reward) > 1e-4:
        mismatch = True
        details.append(f"Reward mismatch: Platform={accrued}, Site={req.total_accrued_reward}")
    if abs(charged - req.total_charged_fee) > 1e-4:
        mismatch = True
        details.append(f"Fee mismatch: Platform={charged}, Site={req.total_charged_fee}")

    return {
        "experiment_id": req.experiment_id,
        "verified": not mismatch,
        "details": details,
        "platform_accrued": accrued,
        "platform_charged": charged
    }

@app.post("/api/v1/federation/secure-test")
def secure_test_api(site_id: str = Depends(verify_signature)):
    return {"status": "authorized", "site_id": site_id}

# ----------------- Settlement Plane (Phase 4) API -----------------

class SettlementConfig(BaseModel):
    provider_type: str

class ObligationCreateRequest(BaseModel):
    experiment_id: str
    agent_id: str
    amount: float

class BatchCreateRequest(BaseModel):
    experiment_id: str
    obligation_ids: list[str]

class ClaimSubmitRequest(BaseModel):
    batch_id: str
    agent_id: str
    amount: float
    nonce: str
    proof: list[str]

CURRENT_PROVIDER_TYPE = "internal"

def get_settlement_provider():
    from app.services.settlement_provider import InternalLedgerSettlementProvider, EvmEscrowSettlementProvider
    if CURRENT_PROVIDER_TYPE == "evm":
        return EvmEscrowSettlementProvider()
    return InternalLedgerSettlementProvider()

@app.post("/api/v1/settlement/config")
def configure_settlement_provider_api(req: SettlementConfig):
    global CURRENT_PROVIDER_TYPE
    if req.provider_type not in ["internal", "evm"]:
        raise HTTPException(status_code=400, detail="Invalid provider_type. Choose 'internal' or 'evm'")
    CURRENT_PROVIDER_TYPE = req.provider_type
    return {"status": "success", "provider_type": CURRENT_PROVIDER_TYPE}

@app.post("/api/v1/settlement/obligations")
def create_obligation_api(req: ObligationCreateRequest, db: Session = Depends(get_db)):
    provider = get_settlement_provider()
    try:
        # reserve_funds 연동 (안전한 자금 홀딩)
        # SYSTEM_REWARD_POOL 계정에 충분한 예산이 확보되어 있어야 함
        provider.reserve_funds(req.experiment_id, req.amount, db)
        ob_id = provider.record_obligation(req.experiment_id, req.agent_id, req.amount, db)
        return {"status": "success", "obligation_id": ob_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/settlement/batches")
def create_settlement_batch_api(req: BatchCreateRequest, db: Session = Depends(get_db)):
    provider = get_settlement_provider()
    try:
        batch_id = provider.create_batch_settlement(req.experiment_id, req.obligation_ids, db)
        return {"status": "success", "batch_id": batch_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/settlement/claims")
def submit_settlement_claim_api(req: ClaimSubmitRequest, db: Session = Depends(get_db)):
    provider = get_settlement_provider()
    try:
        claim_id = provider.submit_claim(
            batch_id=req.batch_id,
            agent_id=req.agent_id,
            amount=req.amount,
            nonce=req.nonce,
            proof=req.proof,
            db=db
        )
        return {"status": "success", "claim_id": claim_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    host = os.getenv("SERVER_HOST", "127.0.0.1")
    port = int(os.getenv("PLATFORM_PORT", os.getenv("SERVER_PORT", "8050")))
    reload_enabled = os.getenv("APP_RELOAD", "false").lower() == "true"
    logger.info(f"[System] Platform Hub Server starting at http://{host}:{port}")
    uvicorn.run("run:app", host=host, port=port, reload=reload_enabled)
