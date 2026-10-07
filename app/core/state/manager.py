from __future__ import annotations

from enum import Enum
import structlog

from app.core.events.bus import EventBus

logger = structlog.get_logger(__name__)

class AppState(str, Enum):
    INITIALIZING = 'initializing'
    READY = 'ready'
    LISTENING = 'listening'
    PROCESSING = 'processing'
    SPEAKING = 'speaking'
    ERROR = 'error'
    SHUTTING_DOWN = 'shutting_down'

class StateManager:
    """Manages the global application state."""
    
    def __init__(self, event_bus: EventBus) -> None:
        self._state: AppState = AppState.INITIALIZING
        self._event_bus = event_bus

    @property
    def state(self) -> AppState:
        """Get the current application state."""
        return self._state

    async def transition(self, new_state: AppState) -> None:
        """Transition application state and publish event."""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            logger.info("State transitioned", old_state=old_state.value, new_state=new_state.value)
            # A specific state changed event could be published here
