# AI Providers

Airi is designed to be model-agnostic. The `AIProvider` interface abstracts away the underlying logic of processing inputs, allowing you to use fast local patterns or advanced cloud models seamlessly.

## AI Router

The system entry point for user input is the AI Router. It performs intent classification on the prompt:
- **Simple Intents** (e.g., "mute volume", "open firefox", "what time is it?") are routed to the Local Provider.
- **Complex Intents** (e.g., "summarize this article", "write a python script") are routed to the active Cloud Provider (if enabled).

## Provider Interface

All AI Providers must implement the `AIProvider` abstract base class:

```python
from abc import ABC, abstractmethod
from app.core.schemas import Message

class AIProvider(ABC):
    @abstractmethod
    async def process(self, messages: list[Message]) -> Message:
        pass
```

## Local Provider

The Local Provider is a blazing fast, zero-dependency engine that uses regex pattern matching and semantic heuristics to map intents to Tool calls. It requires no GPU, no internet, and guarantees absolute privacy for system commands.

## OpenAI Provider

The OpenAI provider uses the official `openai` Python package. It supports Function Calling to execute tools automatically based on natural language prompts.

### Configuration
Set the following in `.env`:
```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

## GPT-6 Astra Readiness

The provider interface is designed asynchronously and supports streaming tokens and multi-modal inputs (images, audio). This ensures Airi is completely ready to integrate the upcoming GPT-6 Astra model's native multimodal capabilities once the API is public.

## Adding a New Provider

To add a provider (e.g., Anthropic, Local LLM via Ollama):
1. Inherit from `AIProvider`.
2. Implement the `process` method.
3. Handle mapping the provider's tool-calling format to Airi's internal Tool Schema.
4. Register the provider in `app/ai/factory.py`.
