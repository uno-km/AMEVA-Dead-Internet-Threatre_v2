from abc import ABC, abstractmethod
from app.core.action import BaseAction

class BaseEnvironment(ABC):
    """
    에이전트가 존재하고 상호작용하는 물리적/논리적 공간(예: Forum, Grid Map)에 대한 추상 클래스
    """
    def __init__(self, env_id: str):
        self.env_id = env_id

    @abstractmethod
    def get_state(self) -> dict:
        """현재 환경의 전체/부분 상태 정보 반환"""
        pass

    @abstractmethod
    def update_state(self, action: BaseAction) -> dict:
        """에이전트가 제출한 액션을 환경 상태에 반영하고 결과 이벤트 반환"""
        pass
