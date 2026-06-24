import time
import json
import logging
import asyncio
from datetime import datetime
from app.web.database import SessionLocal
from app.web.models import ActiveNode, AuditEvent, Reputation
from app.services.event_bus import get_event_bus
from app.web.websocket_router import manager

logger = logging.getLogger("PlatformConsumers")

class FanoutNotifierConsumer:
    """
    플랫폼 측 백그라운드 소비자.
    확정된 도메인 이벤트를 읽어와 관련 웹소켓 세션 채널 클라이언트들에게 일괄 브로드캐스트합니다.
    """
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self.domain_stream = f"ameva:exp:{experiment_id}:domain"
        self.group_name = "fanout-notifiers"
        self.consumer_name = "platform_notifier_1"
        self.bus = get_event_bus()
        
        # 소비자 그룹 생성
        self.bus.create_consumer_group(self.domain_stream, self.group_name)

    async def start_loop(self):
        logger.info(f"FanoutNotifierConsumer started for experiment {self.experiment_id}")
        while True:
            try:
                processed = await self.process_next()
                if processed == 0:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in FanoutNotifierConsumer loop: {e}")
                await asyncio.sleep(2.0)

    async def process_next(self) -> int:
        events = self.bus.read_group(self.domain_stream, self.group_name, self.consumer_name, count=10, block_ms=1000)
        if not events:
            return 0
            
        for msg_id, envelope in events:
            # 실시간 웹소켓 브로드캐스트 수행
            await manager.broadcast(envelope, self.experiment_id)
            self.bus.ack(self.domain_stream, self.group_name, msg_id)
            
        return len(events)

class PresenceMonitor:
    """
    플랫폼 측 백그라운드 태스크.
    ActiveNode 테이블을 스캔하여 하트비트 시간 초과에 따라 세션을 만료시키고 에이전트 평판 지표를 갱신합니다.
    """
    def __init__(self):
        pass

    async def start_loop(self):
        logger.info("PresenceMonitor loop started")
        while True:
            try:
                await self.check_presence()
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in PresenceMonitor loop: {e}")
                await asyncio.sleep(5.0)

    async def check_presence(self):
        db = SessionLocal()
        try:
            now = datetime.now()
            nodes = db.query(ActiveNode).all()
            for node in nodes:
                delta = (now - node.last_seen).total_seconds()
                if delta > 30.0:
                    if node.status != "OFFLINE":
                        node.status = "OFFLINE"
                        logger.info(f"PresenceMonitor: Node '{node.bot_name}' offline (no ping for {delta:.1f}s)")
                        
                        # 평판(Reputation) 업데이트
                        rep = db.query(Reputation).filter_by(agent_id=node.bot_name).first()
                        if not rep:
                            rep = Reputation(agent_id=node.bot_name, offline_count=1, score=95.0)
                            db.add(rep)
                        else:
                            rep.offline_count += 1
                            rep.score = max(0.0, rep.score - 5.0)

                        # 자동 재할당(Reassignment) 연동
                        from app.services.dispatcher_service import DispatcherService
                        from app.web.models import DispatchAssignment
                        
                        worker_node_id = node.node_id[5:] if node.node_id.startswith("node_") else node.node_id
                        assignments = db.query(DispatchAssignment).filter_by(
                            node_id=worker_node_id,
                            status="ASSIGNED"
                        ).all()
                        
                        for assign in assignments:
                            try:
                                DispatcherService.reassign_experiment(db, assign.experiment_id, worker_node_id)
                            except Exception as re_err:
                                logger.error(f"Reassignment failed for experiment {assign.experiment_id} on node {worker_node_id}: {re_err}")
                elif delta > 15.0:
                    if node.status != "DEGRADED":
                        node.status = "DEGRADED"
                        logger.info(f"PresenceMonitor: Node '{node.bot_name}' degraded (no ping for {delta:.1f}s)")
                else:
                    if node.status in ["OFFLINE", "DEGRADED"]:
                        from app.web.models import ExperimentSpec, DispatchAssignment
                        is_assigned_active = False
                        assignment = db.query(DispatchAssignment).filter_by(agent_id=node.bot_name, status="ASSIGNED").first()
                        if assignment:
                            spec = db.query(ExperimentSpec).filter_by(experiment_id=assignment.experiment_id).first()
                            if spec and spec.status == "RUNNING":
                                is_assigned_active = True
                        node.status = "ACTIVE" if is_assigned_active else "LOBBY_WAITING"
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"PresenceMonitor error: {e}")
        finally:
            db.close()

