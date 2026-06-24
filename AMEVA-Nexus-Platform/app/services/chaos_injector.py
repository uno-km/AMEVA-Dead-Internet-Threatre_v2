import asyncio
import random
import logging

logger = logging.getLogger("ChaosInjector")

class ChaosInjector:
    def __init__(self):
        self.latency_ms = 0
        self.drop_rate = 0.0          # 0.0 ~ 1.0
        self.duplicate_rate = 0.0      # 0.0 ~ 1.0

    def configure(self, config: dict):
        self.latency_ms = int(config.get("latency_ms", 0))
        self.drop_rate = float(config.get("drop_rate", 0.0))
        self.duplicate_rate = float(config.get("duplicate_rate", 0.0))
        logger.info(f"Chaos config updated: latency={self.latency_ms}ms, drop_rate={self.drop_rate}, duplicate_rate={self.duplicate_rate}")

    async def inject_chaos(self):
        """비동기 지연 및 패킷 유실 카오스 주입"""
        if self.latency_ms > 0:
            logger.warning(f"[Chaos] Injecting latency of {self.latency_ms}ms")
            await asyncio.sleep(self.latency_ms / 1000.0)
            
        if self.drop_rate > 0.0:
            if random.random() < self.drop_rate:
                logger.error("[Chaos] Injecting packet drop error")
                raise RuntimeError("Chaos injected failure: Packet drop simulation")

    def inject_chaos_sync(self):
        """동기 지연 및 패킷 유실 카오스 주입"""
        import time
        if self.latency_ms > 0:
            logger.warning(f"[Chaos] Injecting latency of {self.latency_ms}ms (Sync)")
            time.sleep(self.latency_ms / 1000.0)
            
        if self.drop_rate > 0.0:
            if random.random() < self.drop_rate:
                logger.error("[Chaos] Injecting packet drop error (Sync)")
                raise RuntimeError("Chaos injected failure: Packet drop simulation (Sync)")

    def should_duplicate(self) -> bool:
        """중복 이벤트 주입 여부 반환"""
        if self.duplicate_rate > 0.0:
            if random.random() < self.duplicate_rate:
                logger.warning("[Chaos] Injecting duplicate event storm")
                return True
        return False

# 글로벌 싱글톤 객체 제공
chaos_injector = ChaosInjector()
