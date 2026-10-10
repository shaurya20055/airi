import pytest
from app.agent.context import AgentContext

def test_intent_routing_instructions_in_prompt():
    ctx = AgentContext()
    sys_prompt = ctx.messages[0].content
    
    assert "execute_command" in sys_prompt
    assert "terminal_open" in sys_prompt
    assert "browser_open" in sys_prompt
    assert "get_gpu_status" in sys_prompt
    assert "enable_hotspot" in sys_prompt
    assert "disable_hotspot" in sys_prompt
    assert "browser_search" in sys_prompt
    assert "launch_application" in sys_prompt



def test_routing_only_references_registered_tools():
    """Every tool named in the routing block must actually be registered."""
    import re
    from app.tools.registry import registry
    from app.tools import register_all_tools
    import app.tools.browser.automation
    import importlib
    
    register_all_tools(registry)
    # the decorator doesn't refire if already imported, so manually register browser_open etc if missing
    importlib.reload(app.tools.browser.automation)
    
    registered = {t.name for t in registry.list_tools()}
    routing = AgentContext().messages[0].content.split("INTENT ROUTING:")[1]
    routing = re.sub(r"\([^)]*\)", "", routing)  # drop parameter lists like (browser_name, query)
    named = set(re.findall(r"([a-z]+_[a-z_]+)", routing))
    missing = {n for n in named if n not in registered}
    assert not missing, f"Routing references unregistered tools: {missing}"
