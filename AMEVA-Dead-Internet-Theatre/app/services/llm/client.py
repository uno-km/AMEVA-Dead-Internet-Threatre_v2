import httpx
import logging
import os
import asyncio

logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str = None, model_name: str = None):
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "http://localhost:11434")
        self.model_name = model_name or os.getenv("LLM_MODEL_NAME", "llama3.1:8b-instruct-q4_K_M")
        self.timeout = float(os.getenv("LLM_TIMEOUT", "180.0"))

    async def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        stop=None,
        timeout: float = None,
        response_format=None,
        temperature: float = 0.8
    ) -> str:
        """
        공유 LLM 서버 API (/v1/chat/completions) 호출
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model_name,
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

        try:
            logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Model: {self.model_name}, Max Tokens: {max_tokens}, Temp: {temperature})")
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
