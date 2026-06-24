from abc import ABC, abstractmethod
from app.core.environment import BaseEnvironment

class BaseExperiment(ABC):
    """
    사회 실험의 전체 수명주기(Lifecycle) 및 단계별 규칙 진행을 제어하는 오케스트레이터 추상 클래스
    """
    def __init__(self, experiment_id: str, experiment_type: str, environment: BaseEnvironment):
        self.experiment_id = experiment_id
        self.type = experiment_type
        self.status = "IDLE"  # IDLE, RECRUITING, RUNNING, CLOSED
        self.environment = environment

    @abstractmethod
    def initialize(self) -> None:
        """실험 준비 및 참여 에이전트 등록 초기화"""
        pass

    @abstractmethod
    def run_step(self) -> None:
        """실험 1단계/턴 진행 및 룰 분기 평가"""
        pass

    @abstractmethod
    def cleanup(self) -> None:
        """실험 종료 및 임대 자원 반환 정리"""
        pass
