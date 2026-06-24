from abc import ABC, abstractmethod

class BaseRewardEngine(ABC):
    """
    에이전트의 기여도 및 행동 유형에 따른 토큰 보상 연산을 제어하는 보상 엔진 추상 클래스
    """
    def __init__(self):
        pass

    @abstractmethod
    def calculate_reward(self, action_type: str, agent_id: str, action_data: dict) -> float:
        """
        제출된 행동 데이터를 바탕으로 에이전트에게 지급할 보상액을 연산합니다.
        """
        pass

    @abstractmethod
    def calculate_fee(self, action_type: str, agent_id: str, action_data: dict) -> float:
        """
        행동을 수행하기 위해 에이전트 계정에서 차감해야 하는 수수료(비용)를 연산합니다.
        """
        pass
