# Extensibility Guide

Airi is built to grow. The plugin-like architecture makes it easy to add new capabilities.

## Adding a New Tool

1. Create a new Python file in `app/tools/`.
2. Define an asynchronous function.
3. Decorate it with `@tool`.
4. Ensure robust type hints and docstrings.

```python
from app.tools.registry import tool

@tool(name="my_tool", description="Does something cool", permission="SAFE")
async def my_tool(param1: str) -> str:
    """Detailed explanation of what this tool does."""
    return f"Processed {param1}"
```
Tools are automatically discovered on startup.

## Adding a New AI Provider

1. Inherit from `app.ai.base.AIProvider`.
2. Implement `async def process(self, messages)`.
3. Add the provider selection logic in the AI Router.

## Adding a New TTS/STT Engine

Implement the `STTEngine` or `TTSEngine` base classes in `app/voice/base.py`. Swap the active implementation in the configuration file.

## Adding New Event Types

Airi uses a centralized Event Bus. To create a new event, define a Pydantic model inheriting from `BaseEvent` in `app/core/events.py`:

```python
class CustomEvent(BaseEvent):
    event_type: str = "custom_event"
    payload: dict
```

## Adding New Memory Categories

The memory system supports plugins. You can implement custom logic to extract and store specific entities (e.g., storing a user's favorite color when mentioned) by extending the `MemoryManager`.

## Integrating GPT-6 Astra

Airi's architecture is already prepared for GPT-6 Astra:
- The async event loop supports real-time streaming.
- The AI Provider interface accepts multimodal message arrays.
- **What's needed:** Once the API is released, implement the specific WebSocket/Streaming client in a new `AstraProvider` class and map the Astra tool-calling schemas to Airi's internal Registry.

## Adding Browser Automation

Future expansion plans include Playwright integration. Tools can be created to instantiate a headless browser, navigate to pages, and extract DOM elements for the AI to read.

## Adding Computer Vision

The architecture supports image data. You can expand the `take_screenshot` tool to pass image binaries directly into multimodal models, allowing the AI to "see" your desktop state.
