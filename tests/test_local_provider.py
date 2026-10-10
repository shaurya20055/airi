import pytest
from app.ai.providers.local.provider import LocalProvider
from app.ai.schemas import IntentType

def test_local_provider_intents():
    provider = LocalProvider()
    
    intent = provider.classify_intent("open Kitty and run echo hello")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "terminal_run_visible"
    assert intent.tool_args["terminal"].lower() == "kitty"
    assert intent.tool_args["command"] == "echo hello"
    
    intent = provider.classify_intent("open Helium and search YouTube for dogs")
    assert intent.type == IntentType.TOOL_CALL
    assert intent.tool_name == "browser_search"
    assert intent.tool_args["browser_name"].lower() == "helium"
    assert intent.tool_args["site"].lower() == "youtube"
    assert intent.tool_args["query"] == "dogs"
