import httpx
import logging

logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.timeout = 600.0

    async def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        stop=None,
        timeout: float = None,
        response_format=None
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
            "temperature": 0.8,
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
            logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Max Tokens: {max_tokens}, Timeout: {req_timeout})")
            async with httpx.AsyncClient(timeout=req_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                logger.info(f"[NETWORK] Received {len(content)} chars from {self.base_url}")
                return content
        except httpx.TimeoutException:
            logger.error(f"[TIMEOUT] LLM API call timed out to {self.base_url}")
            return ""
        except Exception as e:
            logger.error(f"[ERROR] LLM API call failed: {e}")
            return ""

