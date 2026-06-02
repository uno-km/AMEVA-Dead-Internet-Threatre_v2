import httpx
import logging

logger = logging.getLogger("LLMClient")

class LLMClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.timeout = 30.0

    async def generate_completion(self, system_prompt: str, user_prompt: str, max_tokens: int = 512, stop=None) -> str:
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
            "temperature": 0.7,
        }
        if stop:
            payload["stop"] = stop

        try:
            logger.info(f"[NETWORK] Routing data to {self.base_url}/v1/chat/completions (Max Tokens: {max_tokens})")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
