import asyncio
import json
import logging
import time
import uuid
import websockets
from app.services.event_bus import get_event_bus
import os

logger = logging.getLogger("PlatformBridge")

class PlatformBridge:
    def __init__(self, experiment_id: str = "EXP_TEST"):
        self.experiment_id = experiment_id
        # 기본 플랫폼 포트 8050 사용
        self.platform_ws_url = os.getenv("PLATFORM_WS_URL", "ws://127.0.0.1:8050")
        self.platform_ws_endpoint = f"{self.platform_ws_url}/ws/v1/experiments/{experiment_id}?agent_id=dit_bridge"
        
        self.bus = get_event_bus()
        self.action_stream = f"ameva:exp:{experiment_id}:actions"
        self.domain_stream = f"ameva:exp:{experiment_id}:domain"
        
        self.group_name = "platform-bridges"
        self.consumer_name = "dit_bridge_sender"
        
        # DIT 로컬의 domain 이벤트를 플랫폼으로 포워딩하기 위한 소비자 그룹 생성
        try:
            self.bus.create_consumer_group(self.domain_stream, self.group_name)
        except Exception as e:
            logger.warning(f"Could not create consumer group in bridge: {e}")

        self._ws = None
        self._running = False

    async def start_loop(self):
        self._running = True
        logger.info(f"Starting PlatformBridge to: {self.platform_ws_endpoint}")
        
        retry_delay = 1.0
        max_delay = 60.0
        
        while self._running:
            try:
                async with websockets.connect(self.platform_ws_endpoint) as ws:
                    self._ws = ws
                    logger.info("Successfully connected to Platform Hub WebSocket!")
                    retry_delay = 1.0
                    
                    # 양방향 포워딩 태스크 실행
                    recv_task = asyncio.create_task(self._recv_from_platform())
                    send_task = asyncio.create_task(self._send_to_platform())
                    hb_task = asyncio.create_task(self._send_heartbeats())
                    
                    done, pending = await asyncio.wait(
                        [recv_task, send_task, hb_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    for task in pending:
                        task.cancel()
                        
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                        
                    for task in done:
                        if task.exception() is not None:
                            raise task.exception()
                            
                    logger.info("PlatformBridge tasks completed. Reconnecting...")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"PlatformBridge connection error: {e}. Retrying in {retry_delay} seconds...")
                self._ws = None
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, max_delay)

    async def _send_heartbeats(self):
        """플랫폼 허브에 dit_bridge 하트비트를 전송하여 활성 노드 유지"""
        while self._ws:
            try:
                hb = {
                    "version": "1.0.0",
                    "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                    "event_type": "agent.heartbeat",
                    "idempotency_key": str(uuid.uuid4()),
                    "timestamp": int(time.time()),
                    "payload": {}
                }
                await self._ws.send(json.dumps(hb))
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Bridge heartbeat failed: {e}")
                raise e

    async def _recv_from_platform(self):
        """플랫폼 허브로부터 온 액션(action.submitted) 및 하트비트를 처리"""
        try:
            async for message in self._ws:
                envelope = json.loads(message)
                event_type = envelope.get("event_type")
                
                if event_type == "action.submitted":
                    logger.info(f"[BRIDGE] Received action from Platform Hub: {envelope.get('event_id')}")
                    # DIT 로컬 event_bus에 publish
                    self.bus.publish(self.action_stream, envelope)
                elif event_type == "agent.heartbeat":
                    agent_id = envelope.get("agent_id")
                    if agent_id:
                        try:
                            import httpx
                            port = os.getenv("DIT_PORT", "8081")
                            async with httpx.AsyncClient() as client:
                                await client.post(f"http://127.0.0.1:{port}/api/nodes/ping", json={
                                    "bot_name": agent_id,
                                    "hardware_mode": "GPU",
                                    "current_activity": "Active in Platform"
                                })
                        except Exception as e:
                            logger.error(f"Failed to forward heartbeat to local ping endpoint: {e}")
                elif envelope.get("type") == "ack":
                    pass # ignore ack
                elif envelope.get("type") == "error":
                    logger.warning(f"[BRIDGE] Error envelope from Platform: {envelope}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in PlatformBridge receive loop: {e}")
            raise e

    async def _send_to_platform(self):
        """DIT 로컬에서 생성된 도메인 이벤트(post.created, comment.created)를 플랫폼 허브로 포워딩"""
        while self._ws:
            try:
                events = self.bus.read_group(self.domain_stream, self.group_name, self.consumer_name, count=5, block_ms=500)
                if not events:
                    await asyncio.sleep(0.5)
                    continue
                    
                for msg_id, envelope in events:
                    logger.info(f"[BRIDGE] Forwarding domain event to Platform: {envelope.get('event_type')}")
                    
                    # websocket을 통해 플랫폼 허브로 발송
                    await self._ws.send(json.dumps(envelope))
                    
                    # ack 처리
                    self.bus.ack(self.domain_stream, self.group_name, msg_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in PlatformBridge send loop: {e}")
                raise e

    def stop(self):
        self._running = False
        if self._ws:
            pass
