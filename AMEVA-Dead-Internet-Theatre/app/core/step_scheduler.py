from abc import ABC, abstractmethod

class BaseStepScheduler(ABC):
    """
    실험의 턴(Turn) 진행 주기 및 각 에이전트의 액션 제출 순서를 조율하는 스케줄러 추상 클래스
    """
    def __init__(self):
        pass

    @abstractmethod
    def schedule_next_step(self, experiment_id: str) -> None:
        """
        다음 실험 단계를 예약하거나 스케줄러 상태를 갱신합니다.
        """
        pass

    @abstractmethod
    def is_step_ready(self, experiment_id: str) -> bool:
        """
        현재 턴/단계 진행이 가능한 상태인지 여부를 판단합니다.
        """
        pass
