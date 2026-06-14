import httpx
import logging
import subprocess
import asyncio
from contextlib import asynccontextmanager

_endpoint_locks = {}

def get_endpoint_lock(base_url: str) -> asyncio.Semaphore:
    if base_url not in _endpoint_locks:
        _endpoint_locks[base_url] = asyncio.Semaphore(1)
    return _endpoint_locks[base_url]
logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str, container_name: str = None):
        self.base_url = base_url
        self.container_name = container_name
        self.timeout = 600.0
        self.auto_lifecycle = True

    async def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        stop=None,
        timeout: float = 180.0,
        response_format=None,
        temperature: float = 0.8
    ) -> str:
        """
        Llama.cpp Server API (/v1/chat/completions) 호출
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "repetition_penalty": 1.05,
            "presence_penalty": 0.4,
            "frequency_penalty": 0.4,
        }
        if stop:
            payload["stop"] = stop
        if response_format:
            payload["response_format"] = response_format

        req_timeout = timeout if timeout is not None else self.timeout

        endpoint_lock = get_endpoint_lock(self.base_url)
        from src.orchestration.state_manager import state_manager
        async with endpoint_lock:
            if self.container_name:
                state_manager.active_llm = self.container_name
            try:
                logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Max Tokens: {max_tokens}, Timeout: {req_timeout}, Temp: {temperature})")
                async with httpx.AsyncClient(timeout=req_timeout) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    logger.info(f"[NETWORK] Received {len(content)} chars from {self.base_url}")
                    return content
            except httpx.TimeoutException:
                logger.error(f"[TIMEOUT] LLM API call timed out to {self.base_url}")
                raise ConnectionError(f"LLM Timeout to {self.base_url}")
            except Exception as e:
                logger.error(f"[ERROR] LLM API call failed: {e}")
                raise ConnectionError(f"LLM API Failed: {e}")
            finally:
                if self.container_name and state_manager.active_llm == self.container_name:
                    state_manager.active_llm = None

    async def start_container(self):
        """도커 컨테이너 구동 및 헬스체크 대기"""
        if not self.container_name:
            return
            
        from src.orchestration.state_manager import state_manager
        
        activity_msg = f"컨테이너 '{self.container_name}' 기동 중..."
        logger.info(f"[LIFECYCLE] {activity_msg}")
        state_manager.current_activity = activity_msg
        
        try:
            # 컨테이너 시작 (docker compose up -d 사용으로 미존재 시 자동 생성)
            service_name = self.container_name.replace("ameva-", "")
            cmd = ["docker", "compose", "-f", "docker/docker-compose.yml"]
            import os
            if os.path.exists("docker/docker-compose.override.yml"):
                cmd.extend(["-f", "docker/docker-compose.override.yml"])
            cmd.extend(["up", "-d", service_name])
            subprocess.run(cmd, check=True, capture_output=True)
            
            waiting_msg = f"'{self.container_name}' API 준비 상태 확인 중..."
            logger.info(f"[LIFECYCLE] '{self.container_name}' started. Waiting for API readiness...")
            state_manager.current_activity = waiting_msg
            
            # API 준비 대기 (Max 120 seconds)
            async with httpx.AsyncClient() as client:
                for _ in range(120):
                    try:
                        res = await client.get(f"{self.base_url}/health", timeout=2.0)
                        if res.status_code == 200:
                            data = res.json()
                            if data.get("status") == "ok":
                                ready_msg = f"'{self.container_name}' API 준비 완료."
                                logger.info(f"[LIFECYCLE] {ready_msg}")
                                state_manager.current_activity = ready_msg
                                return
                    except httpx.RequestError:
                        pass
                    await asyncio.sleep(2.0)
                    
            logger.warning(f"[LIFECYCLE] Timeout waiting for '{self.container_name}' readiness, but proceeding anyway.")
        except Exception as e:
            logger.error(f"[LIFECYCLE ERROR] Failed to start '{self.container_name}': {e}")

    async def stop_container(self):
        """도커 컨테이너 종료"""
        if not self.container_name:
            return
            
        from src.orchestration.state_manager import state_manager
        
        activity_msg = f"컨테이너 '{self.container_name}' 종료 중..."
        logger.info(f"[LIFECYCLE] {activity_msg}")
        state_manager.current_activity = activity_msg
        
        try:
            service_name = self.container_name.replace("ameva-", "")
            cmd = ["docker", "compose", "-f", "docker/docker-compose.yml"]
            import os
            if os.path.exists("docker/docker-compose.override.yml"):
                cmd.extend(["-f", "docker/docker-compose.override.yml"])
            cmd.extend(["stop", service_name])
            subprocess.run(cmd, check=True, capture_output=True)
            
            stopped_msg = f"'{self.container_name}' 종료 완료."
            logger.info(f"[LIFECYCLE] {stopped_msg}")
            state_manager.current_activity = stopped_msg
        except Exception as e:
            logger.error(f"[LIFECYCLE ERROR] Failed to stop '{self.container_name}': {e}")

    @asynccontextmanager
    async def lifecycle(self):
        """필요할 때만 컨테이너를 켜고 끄는 Context Manager"""
        if self.auto_lifecycle:
            await self.start_container()
        try:
            yield
        finally:
            if self.auto_lifecycle:
                await self.stop_container()

