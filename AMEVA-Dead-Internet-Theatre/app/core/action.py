from abc import ABC, abstractmethod

class BaseAction(ABC):
    """
    AMEVA vNext 에이전트의 의사결정 및 행동에 대한 최상위 추상 클래스
    """
    def __init__(self, agent_id: str, action_type: str, payload: dict):
        self.agent_id = agent_id
        self.action_type = action_type
        self.payload = payload

    @abstractmethod
    def validate(self) -> bool:
        """액션 페이로드의 정합성 및 포맷 유효성 검증"""
        pass
