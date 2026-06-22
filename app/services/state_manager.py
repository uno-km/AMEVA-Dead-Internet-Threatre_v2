import asyncio
import logging
from enum import Enum

logger = logging.getLogger("StateManager")

class SystemState(Enum):
    IDLE = "IDLE"           # No session running, wait for 'new' or 'restart'
    RUNNING = "RUNNING"     # Actively generating responses
    PAUSING = "PAUSING"     # Waiting for the current LLM step to finish before pausing
    PAUSED = "PAUSED"       # Fully paused, waiting for 'resume'
    STOPPING = "STOPPING"   # Waiting for the current step to finish before aborting the session
    ERROR = "ERROR"         # System encountered a critical error

class Checkpoint(Enum):
    NONE = "NONE"
    TOPIC_GEN_DONE = "TOPIC_GEN_DONE"
    PHASE1_DONE = "PHASE1_DONE"
    TURN_DONE = "TURN_DONE"

class OrchestratorState:
    def __init__(self):
        self.state = SystemState.IDLE
        self.checkpoint = Checkpoint.NONE
        self.current_session_id = None
        self.current_turn_idx = 0
        self.is_command_running = False
        
        # event is SET when it's allowed to proceed (RUNNING)
        # event is CLEARED when it should wait (PAUSED/IDLE)
        self.proceed_event = asyncio.Event()
        # Initially, do not proceed automatically
        self.proceed_event.clear()

        # Error notification queue / fields
        self.last_error_message = None
        self.current_activity = "대기 중..."
        self.inference_mode = "sequential"
        
        # Local native server parameters
        self.llama_server_path = "llama-server"
        self.model_main = ""
        self.hardware_mode = "cpu"
        self.active_llm = None

    def push_event(self, event_type: str, data: dict):
        if event_type == "ERROR":
            self.last_error_message = data.get("message", "Unknown Error")
            logger.error(f"[EVENT] Pushed ERROR: {self.last_error_message}")

    def set_state(self, new_state: SystemState):
        logger.info(f"[STATE] Transition: {self.state.value} -> {new_state.value}")
        self.state = new_state
        if new_state == SystemState.RUNNING:
            self.proceed_event.set()
        elif new_state in [SystemState.PAUSED, SystemState.IDLE]:
            self.proceed_event.clear()

    async def wait_at_checkpoint(self, cp: Checkpoint, turn_idx: int = 0):
        """
        오케스트레이터가 주요 작업을 완료한 직후 호출합니다.
        상태가 PAUSING이면 PAUSED로 변경하고 대기합니다.
        상태가 STOPPING이면 예외를 발생시켜 세션을 종료합니다.
        """
        self.checkpoint = cp
        self.current_turn_idx = turn_idx
        
        if self.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")

        if self.state == SystemState.PAUSING:
            self.set_state(SystemState.PAUSED)
        
        if self.state == SystemState.PAUSED or self.state == SystemState.IDLE:
            logger.info(f"[CHECKPOINT] Execution paused at {cp.value} (turn {turn_idx}). Waiting for resume...")
            await self.proceed_event.wait()
            logger.info(f"[CHECKPOINT] Resuming from {cp.value} (turn {turn_idx})...")

        if self.state == SystemState.STOPPING:
            raise InterruptedError("SESSION_STOPPED")

state_manager = OrchestratorState()
