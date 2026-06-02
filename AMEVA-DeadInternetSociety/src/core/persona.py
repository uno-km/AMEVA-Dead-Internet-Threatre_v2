import json
import asyncio
from pathlib import Path
from typing import Dict

class PersonaManager:
    """
    JSON 기반 동적 성격 제어를 담당하는 I/O 매니저.
    동시성 충돌을 방지하기 위해 asyncio.Lock을 활용한 메모리 캐시 동기화를 구현함.
    """
    _instance = None
    _lock = asyncio.Lock()
    _file_path = Path("personas.json")
    _cache: Dict[str, str] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_persona(cls, bot_name: str) -> str:
        """특정 봇의 현재 성격(시스템 프롬프트)을 로드"""
        async with cls._lock:
            if not cls._cache:
                cls._load_from_disk()
            return cls._cache.get(bot_name, "너는 평화를 사랑하는 로봇이다.")

    @classmethod
    async def get_all_personas(cls) -> Dict[str, str]:
        """모든 봇의 성격을 반환"""
        async with cls._lock:
            if not cls._cache:
                cls._load_from_disk()
            return cls._cache.copy()

    @classmethod
    async def update_personas(cls, new_personas: Dict[str, str]):
        """갓 LLM이 평가한 결과에 따라 personas.json을 덮어씀"""
        async with cls._lock:
            # 캐시 업데이트
            cls._cache.update(new_personas)
            # 디스크(JSON)에 덮어쓰기
            cls._save_to_disk()

    @classmethod
    async def reset_personas(cls):
        """[경찰 출동 로직] 공격성 임계치 초과 시 평화를 사랑하는 로봇으로 강제 리셋"""
        peace_prompt = "너는 평화를 사랑하는 로봇이다."
        async with cls._lock:
            cls._cache = {
                "bot_1": peace_prompt,
                "bot_2": peace_prompt,
                "bot_3": peace_prompt
            }
            cls._save_to_disk()

    @classmethod
    def _load_from_disk(cls):
        """디스크에서 JSON 파일을 읽어 메모리 캐시에 로드"""
        if not cls._file_path.exists():
            # 초기 성격 셋업
            cls._cache = {
                "bot_1": "너는 매우 시니컬하고 차가운 봇이다.",
                "bot_2": "너는 열정적이고 항상 흥분해 있는 봇이다.",
                "bot_3": "너는 음모론을 믿고 의심이 많은 봇이다."
            }
            cls._save_to_disk()
        else:
            try:
                with open(cls._file_path, "r", encoding="utf-8") as f:
                    cls._cache = json.load(f)
            except Exception:
                cls._cache = {}

    @classmethod
    def _save_to_disk(cls):
        """메모리 캐시를 디스크(JSON 파일)에 저장"""
        with open(cls._file_path, "w", encoding="utf-8") as f:
            json.dump(cls._cache, f, ensure_ascii=False, indent=4)
