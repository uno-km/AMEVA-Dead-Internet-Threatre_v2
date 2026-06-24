import time
import logging
import json
from datetime import datetime
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session

from app.web.database import SessionLocal
from app.web.models import AuditEvent, ActiveNode
from app.services.event_bus import get_event_bus

logger = logging.getLogger("WebSocketGateway")
router = APIRouter()

# Connection Manager for routing domain events back to active agent sockets
class ConnectionManager:
    def __init__(self):
        # experiment_id -> agent_id -> WebSocket
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, experiment_id: str, agent_id: str, websocket: WebSocket):
        await websocket.accept()
        if experiment_id not in self.active_connections:
            self.active_connections[experiment_id] = {}
        self.active_connections[experiment_id][agent_id] = websocket
        logger.info(f"Agent '{agent_id}' connected to experiment '{experiment_id}'")
        try:
            from app.services.observability import metrics
            total_conns = sum(len(conns) for conns in self.active_connections.values())
            metrics.set_gauge("active_websocket_connections", total_conns)
        except Exception as e:
            logger.warning(f"Failed to update metric for connect: {e}")

    def disconnect(self, experiment_id: str, agent_id: str):
        if experiment_id in self.active_connections:
            if agent_id in self.active_connections[experiment_id]:
                del self.active_connections[experiment_id][agent_id]
            if not self.active_connections[experiment_id]:
                del self.active_connections[experiment_id]
        logger.info(f"Agent '{agent_id}' disconnected from experiment '{experiment_id}'")
        try:
            from app.services.observability import metrics
            total_conns = sum(len(conns) for conns in self.active_connections.values())
            metrics.set_gauge("active_websocket_connections", total_conns)
        except Exception as e:
            logger.warning(f"Failed to update metric for disconnect: {e}")

    async def send_personal_message(self, message: dict, experiment_id: str, agent_id: str):
        if experiment_id in self.active_connections and agent_id in self.active_connections[experiment_id]:
            await self.active_connections[experiment_id][agent_id].send_json(message)

    async def broadcast(self, message: dict, experiment_id: str):
        if experiment_id in self.active_connections:
            for agent_id, connection in list(self.active_connections[experiment_id].items()):
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.warning(f"Failed to broadcast to {agent_id}: {e}")

manager = ConnectionManager()

# Memory-based idempotency cache (Short TTL)
# idempotency_key -> timestamp
GATEWAY_IDEMPOTENCY_CACHE: Dict[str, float] = {}

def is_duplicate(idem_key: str) -> bool:
    now = time.time()
    # Prune old keys (older than 5 minutes)
    for key, ts in list(GATEWAY_IDEMPOTENCY_CACHE.items()):
        if now - ts > 300.0:
            del GATEWAY_IDEMPOTENCY_CACHE[key]
            
    if idem_key in GATEWAY_IDEMPOTENCY_CACHE:
        return True
    GATEWAY_IDEMPOTENCY_CACHE[idem_key] = now
    return False

@router.websocket("/ws/v1/experiments/{experiment_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    experiment_id: str,
    agent_id: str = Query(...)
):
    await manager.connect(experiment_id, agent_id, websocket)
    db = SessionLocal()
    bus = get_event_bus()

    # Log connection established to Audit Log and register ActiveNode
    try:
        from app.web.models import ExperimentSpec
        is_active_exp = False
        if experiment_id != "LOBBY":
            spec = db.query(ExperimentSpec).filter_by(experiment_id=experiment_id).first()
            if spec:
                from app.web.models import DispatchAssignment
                assignment = db.query(DispatchAssignment).filter_by(
                    experiment_id=experiment_id,
                    node_id=agent_id,
                    status="ASSIGNED"
                ).first()
                if not assignment:
                    assignment = db.query(DispatchAssignment).filter_by(
                        experiment_id=experiment_id,
                        agent_id=agent_id,
                        status="ASSIGNED"
                    ).first()
                
                if assignment:
                    is_active_exp = True
                else:
                    if spec.status == "RECRUITING":
                        from app.services.dispatcher_service import DispatcherService
                        # 최초/추가 매칭 트리거
                        assignments = DispatcherService.dispatch_experiment(db, experiment_id)
                        is_active_exp = any(a.node_id == agent_id or a.agent_id == agent_id for a in assignments)
                    elif spec.status == "RUNNING":
                        from app.services.dispatcher_service import DispatcherService
                        is_active_exp = DispatcherService.try_late_join(db, experiment_id, agent_id, agent_id)
            else:
                # Default to ACTIVE if spec doesn't exist (legacy tests support)
                is_active_exp = True
        
        status_val = "ACTIVE" if is_active_exp else "LOBBY_WAITING"
        activity_val = "WebSocket Connected" if is_active_exp else "LOBBY Waiting"

        node = db.query(ActiveNode).filter_by(node_id=f"node_{agent_id}").first()
        if not node:
            node = db.query(ActiveNode).filter_by(bot_name=agent_id).first()
        if not node:
            node = ActiveNode(
                node_id=f"node_{agent_id}",
                bot_name=agent_id,
                status=status_val,
                hardware_mode="CPU",
                current_activity=activity_val,
                last_seen=datetime.now()
            )
            db.add(node)
        else:
            node.status = status_val
            node.current_activity = activity_val
            node.last_seen = datetime.now()
        
        audit = AuditEvent(
            event_type="connection.established",
            tenant_id="SYSTEM",
            experiment_id=experiment_id,
            agent_id=agent_id,
            payload_json=json.dumps({"status": "connected"})
        )
        db.add(audit)
        db.commit()
    except Exception as ae:
        logger.error(f"Audit / ActiveNode registration failed: {ae}")
        db.rollback()

    try:
        while True:
            # Receive text / json from socket
            data_text = await websocket.receive_text()
            try:
                envelope = json.loads(data_text)
            except ValueError:
                # Invalid JSON schema
                await websocket.send_json({
                    "type": "error",
                    "error_code": "INVALID_JSON",
                    "message": "Payload is not valid JSON"
                })
                continue

            # 1. Envelope validation against EventEnvelope (v1.0.0)
            required_fields = ["version", "event_id", "event_type", "idempotency_key", "timestamp", "payload"]
            missing = [f for f in required_fields if f not in envelope]
            if missing:
                await websocket.send_json({
                    "type": "error",
                    "error_code": "INVALID_SCHEMA",
                    "message": f"Missing required fields: {missing}"
                })
                continue

            # 표준 Event Envelope에 부합하도록 누락 필드 보조 주입 (Default injection)
            import uuid
            envelope.setdefault("schema_version", "1.0.0")
            envelope.setdefault("producer", agent_id)
            envelope.setdefault("experiment_id", experiment_id)
            envelope.setdefault("session_id", "1")
            envelope.setdefault("trace_id", f"tr_{uuid.uuid4().hex[:12]}")
            envelope.setdefault("correlation_id", f"corr_{uuid.uuid4().hex[:12]}")

            # Type and payload contents validation
            event_type = envelope.get("event_type")
            idem_key = envelope.get("idempotency_key")
            event_id = envelope.get("event_id")

            # Check if this is a heartbeat event or action.submitted
            if event_type == "agent.heartbeat":
                # Heartbeat proxy: Update database status and reply ACK
                try:
                    node = db.query(ActiveNode).filter_by(bot_name=agent_id).first()
                    if node:
                        if node.status in ["OFFLINE", "DEGRADED"]:
                            from app.web.models import ExperimentSpec, DispatchAssignment
                            is_assigned_active = False
                            assignment = db.query(DispatchAssignment).filter_by(agent_id=agent_id, status="ASSIGNED").first()
                            if assignment:
                                spec = db.query(ExperimentSpec).filter_by(experiment_id=assignment.experiment_id).first()
                                if spec and spec.status == "RUNNING":
                                    is_assigned_active = True
                            node.status = "ACTIVE" if is_assigned_active else "LOBBY_WAITING"
                        node.last_seen = datetime.now()
                        node.current_activity = "Heartbeat Received"
                        db.commit()
                except Exception as e:
                    db.rollback()
                    logger.error(f"Heartbeat DB update failed: {e}")

                await websocket.send_json({
                    "type": "ack",
                    "event_id": event_id,
                    "accepted": True,
                    "received_at": datetime.now().isoformat()
                })
                continue

            if event_type not in ["action.submitted", "agent.heartbeat", "post.created", "comment.created"]:
                await websocket.send_json({
                    "type": "error",
                    "error_code": "UNSUPPORTED_EVENT_TYPE",
                    "message": "Gateway only accepts 'action.submitted', 'agent.heartbeat', or domain events from bridge"
                })
                continue

            if event_type in ["post.created", "comment.created"]:
                stream_name = f"ameva:exp:{experiment_id}:domain"
                try:
                    bus.publish(stream_name, envelope)
                    # Broadcast the domain event to all connected agent nodes
                    await manager.broadcast(envelope, experiment_id)
                except Exception as e:
                    logger.error(f"Event bus publish failed for domain event: {e}")
                    await websocket.send_json({
                        "type": "error",
                        "event_id": event_id,
                        "error_code": "EVENT_BUS_FAILURE",
                        "message": "Failed to append event to streaming bus"
                    })
                    continue
                await websocket.send_json({
                    "type": "ack",
                    "event_id": event_id,
                    "accepted": True,
                    "received_at": datetime.now().isoformat()
                })
                continue

            # 2. Gateway-level Fast Idempotency Check
            if is_duplicate(idem_key):
                # Write to audit log
                try:
                    audit = AuditEvent(
                        event_type="action.rejected",
                        tenant_id="SYSTEM",
                        experiment_id=experiment_id,
                        agent_id=agent_id,
                        payload_json=json.dumps({"event_id": event_id, "reason": "DUPLICATE_IDEMPOTENCY_KEY"})
                    )
                    db.add(audit)
                    db.commit()
                except:
                    db.rollback()

                await websocket.send_json({
                    "type": "error",
                    "event_id": event_id,
                    "error_code": "DUPLICATE_IDEMPOTENCY_KEY",
                    "message": "Event already processed"
                })
                continue

            # 3. Append to Event Bus (Actions Stream)
            stream_name = f"ameva:exp:{experiment_id}:actions"
            try:
                node = db.query(ActiveNode).filter_by(bot_name=agent_id).first()
                if node:
                    node.last_seen = datetime.now()
                    node.current_activity = "Sending Action"
                db.commit()
                bus.publish(stream_name, envelope)
                # dit_bridge가 연결되어 있다면 dit_bridge에게 이 액션을 직접 포워딩해줌
                await manager.send_personal_message(envelope, experiment_id, "dit_bridge")
            except Exception as e:
                db.rollback()
                logger.error(f"Event bus publish failed: {e}")
                await websocket.send_json({
                    "type": "error",
                    "event_id": event_id,
                    "error_code": "EVENT_BUS_FAILURE",
                    "message": "Failed to append event to streaming bus"
                })
                continue

            # 4. Immediate Thin Gateway ACK Response
            await websocket.send_json({
                "type": "ack",
                "event_id": event_id,
                "accepted": True,
                "received_at": datetime.now().isoformat()
            })

    except WebSocketDisconnect:
        manager.disconnect(experiment_id, agent_id)
        # Log disconnect to Audit Log and mark Node as OFFLINE
        try:
            node = db.query(ActiveNode).filter_by(bot_name=agent_id).first()
            if node:
                node.status = "OFFLINE"
                node.current_activity = "WebSocket Disconnected"
            
            audit = AuditEvent(
                event_type="connection.closed",
                tenant_id="SYSTEM",
                experiment_id=experiment_id,
                agent_id=agent_id,
                payload_json=json.dumps({"status": "disconnected"})
            )
            db.add(audit)
            db.commit()
        except Exception as err:
            logger.error(f"Disconnect Audit/ActiveNode failed: {err}")
            db.rollback()
    finally:
        db.close()
