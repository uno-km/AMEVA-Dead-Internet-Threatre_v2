from abc import ABC, abstractmethod

class BasePolicyEngine(ABC):
    """
    에이전트의 페르소나 준수 여부 및 시뮬레이션 지침(Directives)을 평가하고 조율하는 정책 엔진 추상 클래스
    """
    def __init__(self):
        pass

    @abstractmethod
    def evaluate_compliance(self, bot_name: str, content: str, directive: str) -> bool:
        """
        에이전트가 생성한 결과물이 현재 지시문(Directive) 및 규칙을 준수하는지 평가합니다.
        """
        pass

    @abstractmethod
    def apply_policy(self, bot_name: str, content: str) -> str:
        """
        입력 텍스트에 정책 필터링이나 수정을 적용합니다.
        """
        pass
