import logging
from typing import List
from src.db.models import Comment

logger = logging.getLogger("PromptAdapter")

GIST_CACHE = {}  # maps (bot_name, raw_content) -> gist string

class PromptAdapter:
    """
    LLM이 이전 대화를 '대본(Script)'으로 착각하고 다른 봇의 발화를 이어쓰는 
    할루시네이션(Hallucination)을 막기 위해, 대화 기록을 메타데이터 형태로 구조화합니다.
    """
    def __init__(self):
        pass

    async def _generate_gist_via_god_llm(self, bot_name: str, msg: str) -> str:
        # Heuristic fallback
        fallback = msg[:50] + "..." if len(msg) > 50 else msg
        try:
            from src.orchestration.runner import god_llm
            prompt = (
                f"Analyze this statement by {bot_name} and summarize their stance/core opinion in one short English phrase (5-10 words).\n"
                f"Do NOT write any meta text, intro, or quotes. Output ONLY the short summary phrase.\n"
                f"Statement: \"{msg}\"\n"
                f"Example: Disagrees with animal sanctuaries and demands stricter regulations."
            )
            result = await god_llm.generate_completion(
                "You are an AI that summarizes forum comments into short stance descriptions.",
                prompt,
                max_tokens=30
            )
            gist = result.strip().strip('"\'')
            if gist:
                return gist
        except Exception as e:
            logger.warning(f"Failed to generate gist via God LLM: {e}")
        return fallback

    async def build_structured_history(self, items: List[dict]) -> str:
        """
        기존 "bot_1: 텍스트" 형식을 탈피하고 요약/스탠스 로그 형태로 변환합니다.
        items는 {"bot_name": ..., "message": ...} 형태의 딕셔너리 리스트입니다.
        출력 포맷: '- bot_name\'s stance: [요약]'
        """
        if not items:
            return "No previous conversation."

        structured_lines = ["[Conversation History]"]
        for item in items:
            bot_name = item.get("bot_name", "Unknown")
            msg = item.get("message", "").strip()
            
            cache_key = (bot_name, msg)
            if cache_key in GIST_CACHE:
                gist = GIST_CACHE[cache_key]
            else:
                gist = await self._generate_gist_via_god_llm(bot_name, msg)
                GIST_CACHE[cache_key] = gist
                
            line = f"- {bot_name}'s stance: {gist}"
            structured_lines.append(line)
        
        return "\n".join(structured_lines)

    def build_prompt(self, agent_state, history: str, target_bot: str) -> str:
        """
        Week 1B에서 적용될 전체 프롬프트 빌더. 
        (1A에서는 Shadow Mode이므로 사용하지 않음)
        """
        pass

prompt_adapter = PromptAdapter()
