import time
import json
import logging
import asyncio
import httpx
from datetime import datetime
from app.web.database import SessionLocal
from app.web.models import Post, Comment, Board
from app.services.event_bus import get_event_bus
import os

logger = logging.getLogger("DITConsumers")

class ActionProcessorConsumer:
    """
    DIT 사회 실험 서버 측 백그라운드 소비자.
    WebSocket Thin Gateway를 통해 플랫폼에 들어온 worker 액션 스트림을 가져와서
    비즈니스 검증 및 포럼 DB(boards, posts, comments) 영속화를 처리합니다.
    금융 정산은 플랫폼 서버의 REST API를 호출하여 비동기 처리합니다.
    """
    def __init__(self, experiment_id: str):
        self.experiment_id = experiment_id
        self.stream_name = f"ameva:exp:{experiment_id}:actions"
        self.domain_stream = f"ameva:exp:{experiment_id}:domain"
        self.group_name = "action-processors"
        self.consumer_name = "dit_processor_1"
        self.bus = get_event_bus()
        
        # 플랫폼 REST API URL
        self.platform_url = os.getenv("PLATFORM_API_URL", "http://127.0.0.1:8050")
        self.mock_platform = os.getenv("ENABLE_INMEMORY_EVENT_BUS", "false").lower() == "true" or os.getenv("MOCK_PLATFORM", "false").lower() == "true"

        # 소비자 그룹 생성
        self.bus.create_consumer_group(self.stream_name, self.group_name)

    async def start_loop(self):
        logger.info(f"ActionProcessorConsumer started for DIT experiment {self.experiment_id}")
        while True:
            try:
                processed = await self.process_next()
                if processed == 0:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ActionProcessorConsumer loop: {e}")
                await asyncio.sleep(2.0)

    async def _call_platform_settlement(self, path: str, payload: dict) -> bool:
        """플랫폼의 정산 REST API를 호출합니다."""
        if self.mock_platform:
            logger.info(f"[MOCK PLATFORM] Bypassing platform API {path} with payload: {payload}")
            return True

        url = f"{self.platform_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Platform settlement success: {resp.json()}")
                    return True
                else:
                    logger.error(f"Platform settlement rejected ({resp.status_code}): {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Platform connection error on {url}: {e}")
            return False

    async def process_next(self) -> int:
        events = self.bus.read_group(self.stream_name, self.group_name, self.consumer_name, count=10, block_ms=1000)
        if not events:
            return 0

        db = SessionLocal()
        try:
            for msg_id, envelope in events:
                event_id = envelope.get("event_id")
                agent_id = envelope.get("agent_id")
                payload = envelope.get("payload", {})
                action_type = payload.get("action_type")
                data = payload.get("data", {})

                # 비즈니스 검증 및 정산 처리
                try:
                    if action_type in ("SUBMIT_COMMENT", "REPLY_COMMENT"):
                        fee = 0.1
                        reward = 1.0
                        
                        # 1. 플랫폼에 행동 수수료 청구 API 호출
                        charge_payload = {
                            "experiment_id": self.experiment_id,
                            "entity_name": agent_id,
                            "amount": fee,
                            "fee_type": "POST_TAX",
                            "description": f"Comment fee for event {event_id}"
                        }
                        settled = await self._call_platform_settlement("/api/v1/settlement/charge", charge_payload)
                        if not settled:
                            raise ValueError("Platform settlement charge failed. Insufficient funds or platform offline.")

                        # 2. 로컬 DIT DB 저장
                        # default board가 없으면 생성
                        board = db.query(Board).filter_by(name="programming").first()
                        if not board:
                            board = Board(board_type="MAJOR", name="programming", description="programming board")
                            db.add(board)
                            db.commit()
                            db.refresh(board)
                        
                        post_id = int(data.get("post_id", 1))
                        comment = Comment(
                            post_id=post_id,
                            parent_id=data.get("parent_id"),
                            bot_name=agent_id,
                            content=data.get("content", ""),
                            mentioned_bot=data.get("mentioned_bot")
                        )
                        db.add(comment)
                        db.commit()
                        db.refresh(comment)
                        
                        # 3. 플랫폼에 기여 보상 적립 API 호출
                        accrue_payload = {
                            "experiment_id": self.experiment_id,
                            "agent_id": agent_id,
                            "amount": reward,
                            "description": f"Comment reward for comment #{comment.id}"
                        }
                        await self._call_platform_settlement("/api/v1/settlement/accrue", accrue_payload)

                        # 4. 확정 도메인 이벤트 발행
                        domain_event = {
                            "version": "1.0.0",
                            "event_id": f"evt_{msg_id}",
                            "event_type": "comment.created",
                            "schema_version": "1.0.0",
                            "experiment_id": self.experiment_id,
                            "session_id": "1",
                            "tenant_id": "SYSTEM",
                            "agent_id": agent_id,
                            "timestamp": int(time.time()),
                            "idempotency_key": envelope.get("idempotency_key"),
                            "trace_id": envelope.get("trace_id", ""),
                            "correlation_id": envelope.get("correlation_id", ""),
                            "payload": {
                                "comment_id": comment.id,
                                "post_id": post_id,
                                "bot_name": agent_id,
                                "content": comment.content
                            }
                        }
                        self.bus.publish(self.domain_stream, domain_event)
                        
                    elif action_type == "SUBMIT_POST":
                        fee = 0.5
                        reward = 2.5
                        
                        # 1. 플랫폼에 행동 수수료 청구 API 호출
                        charge_payload = {
                            "experiment_id": self.experiment_id,
                            "entity_name": agent_id,
                            "amount": fee,
                            "fee_type": "POST_TAX",
                            "description": f"Post fee for event {event_id}"
                        }
                        settled = await self._call_platform_settlement("/api/v1/settlement/charge", charge_payload)
                        if not settled:
                            raise ValueError("Platform settlement charge failed. Insufficient funds or platform offline.")
                        
                        board = db.query(Board).filter_by(name="programming").first()
                        if not board:
                            board = Board(board_type="MAJOR", name="programming", description="programming board")
                            db.add(board)
                            db.commit()
                            db.refresh(board)

                        # 2. 로컬 DIT DB 저장
                        post = Post(
                            board_id=board.id,
                            session_id=1,
                            title=data.get("title", "New Agora Post"),
                            content=data.get("content", "")
                        )
                        db.add(post)
                        db.commit()
                        db.refresh(post)
                        
                        # 3. 플랫폼에 기여 보상 적립 API 호출
                        accrue_payload = {
                            "experiment_id": self.experiment_id,
                            "agent_id": agent_id,
                            "amount": reward,
                            "description": f"Post reward for post #{post.id}"
                        }
                        await self._call_platform_settlement("/api/v1/settlement/accrue", accrue_payload)
                        
                        # 4. 확정 도메인 이벤트 발행
                        domain_event = {
                            "version": "1.0.0",
                            "event_id": f"evt_{msg_id}",
                            "event_type": "post.created",
                            "schema_version": "1.0.0",
                            "experiment_id": self.experiment_id,
                            "session_id": "1",
                            "tenant_id": "SYSTEM",
                            "agent_id": agent_id,
                            "timestamp": int(time.time()),
                            "idempotency_key": envelope.get("idempotency_key"),
                            "trace_id": envelope.get("trace_id", ""),
                            "correlation_id": envelope.get("correlation_id", ""),
                            "payload": {
                                "post_id": post.id,
                                "title": post.title,
                                "content": post.content
                            }
                        }
                        self.bus.publish(self.domain_stream, domain_event)
                        
                    else:
                        raise ValueError(f"Unknown action type: {action_type}")
                        
                except Exception as err:
                    db.rollback()
                    logger.warning(f"Action processing failed for event {event_id}: {err}")
                    
                    reject_event = {
                        "version": "1.0.0",
                        "event_id": f"evt_err_{msg_id}",
                        "event_type": "action.rejected",
                        "schema_version": "1.0.0",
                        "experiment_id": self.experiment_id,
                        "session_id": "1",
                        "tenant_id": "SYSTEM",
                        "agent_id": agent_id,
                        "timestamp": int(time.time()),
                        "idempotency_key": envelope.get("idempotency_key"),
                        "trace_id": envelope.get("trace_id", ""),
                        "correlation_id": envelope.get("correlation_id", ""),
                        "payload": {
                            "error_code": "VALIDATION_FAILED",
                            "message": str(err)
                        }
                    }
                    self.bus.publish(self.domain_stream, reject_event)
                    
                # 스트림 ACK
                self.bus.ack(self.stream_name, self.group_name, msg_id)
                
            return len(events)
        finally:
            db.close()
