from abc import ABC, abstractmethod

class BaseObservationModel(ABC):
    """
    에이전트가 환경에서 관측할 수 있는 데이터의 필터링 및 텐서 변환을 제어하는 관측 모델 추상 클래스
    """
    def __init__(self):
        pass

    @abstractmethod
    def get_observation(self, env_state: dict, agent_id: str) -> dict:
        """
        전체 환경 상태(environment state)를 특정 에이전트 시점의 관측 데이터(observation)로 가공하여 반환합니다.
        """
        pass
