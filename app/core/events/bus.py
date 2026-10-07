from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Type, Awaitable
from collections import defaultdict
import structlog

from app.core.events.events import Event

logger = structlog.get_logger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]

class EventBus:
    """Async event bus for decoupled component communication."""
    
    def __init__(self) -> None:
        """Initialize the event bus."""
        self._subscribers: Dict[Type[Event], List[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: Type[Event], handler: EventHandler) -> None:
        """Subscribe an async handler to a specific event type."""
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed to event", event_type=event_type.__name__, handler=handler.__name__)

    def unsubscribe(self, event_type: Type[Event], handler: EventHandler) -> None:
        """Unsubscribe a handler from a specific event type."""
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)
            logger.debug("Unsubscribed from event", event_type=event_type.__name__, handler=handler.__name__)

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers asynchronously without waiting."""
        handlers = self._subscribers.get(type(event), [])
        if not handlers:
            return
            
        for handler in handlers:
            asyncio.create_task(self._handle_event(handler, event))

    async def publish_and_wait(self, event: Event) -> None:
        """Publish an event and wait for all handlers to complete."""
        handlers = self._subscribers.get(type(event), [])
        if handlers:
            await asyncio.gather(*(self._handle_event(handler, event) for handler in handlers))

    async def _handle_event(self, handler: EventHandler, event: Event) -> None:
        """Execute a single handler for an event safely."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "Error handling event", 
                event_type=type(event).__name__, 
                handler=handler.__name__, 
                error=str(e),
                exc_info=True
            )
