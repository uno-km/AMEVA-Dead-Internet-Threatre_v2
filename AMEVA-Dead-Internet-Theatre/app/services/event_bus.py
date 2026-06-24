import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple, Any

logger = logging.getLogger("EventBus")

class BaseEventBus(ABC):
    @abstractmethod
    def publish(self, stream_name: str, event: dict) -> str:
        pass

    @abstractmethod
    def create_consumer_group(self, stream_name: str, group_name: str) -> None:
        pass

    @abstractmethod
    def read_group(self, stream_name: str, group_name: str, consumer_name: str, count: int = 10, block_ms: int = 2000, start_id: str = ">") -> List[Tuple[str, dict]]:
        pass

    @abstractmethod
    def ack(self, stream_name: str, group_name: str, message_id: str) -> None:
        pass

class RedisStreamEventBus(BaseEventBus):
    def __init__(self, redis_url: str):
        import redis
        self.redis_url = redis_url
        self.client = redis.from_url(redis_url, decode_responses=True)
        logger.info(f"RedisStreamEventBus connected to {redis_url}")

    def publish(self, stream_name: str, event: dict) -> str:
        import json
        try:
            from app.services.chaos_injector import chaos_injector
        except ImportError:
            class MockChaosInjector:
                def inject_chaos_sync(self): pass
                def should_duplicate(self): return False
            chaos_injector = MockChaosInjector()
        
        # 카오스 지연/유실 주입
        try:
            chaos_injector.inject_chaos_sync()
        except Exception as ce:
            logger.error(f"[Chaos] Injected publish failure: {ce}")
            raise ce

        flat_event = {"envelope": json.dumps(event, ensure_ascii=False)}
        msg_id = self.client.xadd(stream_name, flat_event)

        # 카오스 중복 주입
        if chaos_injector.should_duplicate():
            self.client.xadd(stream_name, flat_event)
            
        return msg_id


    def create_consumer_group(self, stream_name: str, group_name: str) -> None:
        try:
            self.client.xgroup_create(stream_name, group_name, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create consumer group {group_name}: {e}")

    def read_group(self, stream_name: str, group_name: str, consumer_name: str, count: int = 10, block_ms: int = 2000, start_id: str = ">") -> List[Tuple[str, dict]]:
        import json
        streams = {stream_name: start_id}
        response = self.client.xreadgroup(group_name, consumer_name, streams, count=count, block=block_ms)
        
        results = []
        if response:
            for stream, messages in response:
                for msg_id, payload in messages:
                    if "envelope" in payload:
                        event_dict = json.loads(payload["envelope"])
                        results.append((msg_id, event_dict))
        return results

    def ack(self, stream_name: str, group_name: str, message_id: str) -> None:
        self.client.xack(stream_name, group_name, message_id)

class InMemoryStreamEventBus(BaseEventBus):
    def __init__(self):
        self.streams: Dict[str, List[Tuple[str, dict]]] = {}
        self.groups: Dict[str, Dict[str, dict]] = {}
        self.seq = 0
        logger.warning(
            "InMemoryStreamEventBus initialized. This is a single-process testing fallback only."
        )

    def _generate_id(self) -> str:
        timestamp = int(time.time() * 1000)
        self.seq += 1
        return f"{timestamp}-{self.seq}"

    def publish(self, stream_name: str, event: dict) -> str:
        try:
            from app.services.chaos_injector import chaos_injector
        except ImportError:
            class MockChaosInjector:
                def inject_chaos_sync(self): pass
                def should_duplicate(self): return False
            chaos_injector = MockChaosInjector()
        
        # 카오스 지연/유실 주입
        try:
            chaos_injector.inject_chaos_sync()
        except Exception as ce:
            logger.error(f"[Chaos] Injected publish failure (InMemory): {ce}")
            raise ce

        if stream_name not in self.streams:
            self.streams[stream_name] = []
        msg_id = self._generate_id()
        self.streams[stream_name].append((msg_id, event))

        # 카오스 중복 주입
        if chaos_injector.should_duplicate():
            dup_id = self._generate_id()
            self.streams[stream_name].append((dup_id, event))

        return msg_id


    def create_consumer_group(self, stream_name: str, group_name: str) -> None:
        if stream_name not in self.groups:
            self.groups[stream_name] = {}
        if group_name not in self.groups[stream_name]:
            self.groups[stream_name][group_name] = {
                "last_delivered_id": "0-0",
                "pending": {}
            }

    def read_group(self, stream_name: str, group_name: str, consumer_name: str, count: int = 10, block_ms: int = 2000, start_id: str = ">") -> List[Tuple[str, dict]]:
        if stream_name not in self.streams:
            self.streams[stream_name] = []
        self.create_consumer_group(stream_name, group_name)
        
        group = self.groups[stream_name][group_name]
        results = []

        if start_id == ">":
            last_id = group["last_delivered_id"]
            new_messages = []
            for msg_id, payload in self.streams[stream_name]:
                if self._is_greater_than(msg_id, last_id):
                    new_messages.append((msg_id, payload))
            
            for msg_id, payload in new_messages[:count]:
                group["pending"][msg_id] = {
                    "consumer": consumer_name,
                    "payload": payload,
                    "delivered_at": time.time()
                }
                group["last_delivered_id"] = msg_id
                results.append((msg_id, payload))
        else:
            for msg_id, info in list(group["pending"].items()):
                if info["consumer"] == consumer_name:
                    results.append((msg_id, info["payload"]))
                    if len(results) >= count:
                        break
                        
        return results

    def ack(self, stream_name: str, group_name: str, message_id: str) -> None:
        if stream_name in self.groups and group_name in self.groups[stream_name]:
            group = self.groups[stream_name][group_name]
            if message_id in group["pending"]:
                del group["pending"][message_id]

    def _is_greater_than(self, id1: str, id2: str) -> bool:
        t1, s1 = map(int, id1.split("-"))
        t2, s2 = map(int, id2.split("-"))
        return (t1 > t2) or (t1 == t2 and s1 > s2)

event_bus: BaseEventBus = None

def init_event_bus() -> BaseEventBus:
    global event_bus
    enable_inmemory = os.getenv("ENABLE_INMEMORY_EVENT_BUS", "true").lower() == "true"
    redis_url = os.getenv("EVENT_BUS_URL", "redis://127.0.0.1:6379/0")

    if enable_inmemory:
        event_bus = InMemoryStreamEventBus()
    else:
        try:
            event_bus = RedisStreamEventBus(redis_url)
        except Exception as e:
            logger.error(f"Failed to connect to Redis, falling back to InMemoryStreamEventBus: {e}")
            event_bus = InMemoryStreamEventBus()
    return event_bus

def get_event_bus() -> BaseEventBus:
    global event_bus
    if event_bus is None:
        return init_event_bus()
    return event_bus
