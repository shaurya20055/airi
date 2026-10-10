"""Regression tests for YouTube video click execution and anti-hallucination verification.

Validates the fix for:
1. "Just click the first video" invokes browser action with YouTube context.
2. "Click on the first video" invokes browser action with YouTube context (no "first video" query pollution).
3. LLM returning "Task completed." without tool invocation does not report success.
4. Tool invocation with failed verification does not report verified completion.
5. Genuine tool execution failure is surfaced correctly.
6. Correction referring to Firefox/current video does not route to launch_application.
7. Missing or stale context does not launch an unrelated app.
8. BrowserTaskContext persists across consecutive voice turns.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agent.orchestrator import AgentOrchestrator
from app.agent.task_context import (
    BrowserTaskContext,
    get_browser_task_context,
    is_browser_result_reference,
    parse_browser_reference,
    set_browser_task_context,
)
from app.agent.tasks import ApplicationClarificationTask
from app.ai.interfaces.provider import AIProvider
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.ai.schemas import AIResponse, Message, ToolCall
from app.core.events.bus import EventBus
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.registry import ToolDefinition, ToolParameter, ToolRegistry, ToolResult, PermissionLevel


@pytest.fixture(autouse=True)
def reset_context():
    """Reset the global browser task context for each test."""
    ctx = BrowserTaskContext()
    set_browser_task_context(ctx)
    yield ctx
    set_browser_task_context(BrowserTaskContext())


@pytest.fixture
def mock_orchestrator(tmp_path):
    from app.tools import register_all_tools
    registry = ToolRegistry()
    register_all_tools(registry)

    event_bus = EventBus()
    permission_manager = PermissionManager(event_bus, cli_mode=True)
    permission_manager.request_permission = AsyncMock(return_value=True)
    memory = MemoryStore(str(tmp_path / "test_mem.db"))
    
    local_provider = LocalProvider()
    router = AIRouter(local_provider, cloud_provider=None)
    
    orchestrator = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=permission_manager,
    )
    return orchestrator, registry, event_bus


# ── 1. "Just click the first video" invokes browser action with YouTube context ─

@pytest.mark.asyncio
async def test_1_just_click_first_video_invokes_browser_action(mock_orchestrator):
    orchestrator, registry, _ = mock_orchestrator
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=ElectroBOOM"
    mock_page.locator.return_value = AsyncMock()

    # Create mock video item
    organic_item = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0
    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=dQw4w9WgXcQ"
    title_link_first.text_content.return_value = "How NOT to Make an Electric Guitar"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator(selector):
        if "ad" in selector:
            return ad_check
        if selector == "a#video-title":
            return title_link
        return AsyncMock()

    organic_item.locator.side_effect = item_locator

    renderers = AsyncMock()
    renderers.count.return_value = 1
    renderers.nth.return_value = organic_item

    def page_locator(selector):
        if selector == "ytd-video-renderer":
            return renderers
        return AsyncMock()

    mock_page.locator.side_effect = page_locator

    async def mock_wait_url(pred, timeout=None):
        mock_page.url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    mock_page.wait_for_url.side_effect = mock_wait_url

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        response = await orchestrator.process_input("Just click the first video")
        assert "Opened video: 'How NOT to Make an Electric Guitar'" in response
        title_link_first.click.assert_called_once()
        assert orchestrator._tools_executed_this_turn is True


# ── 2. "Click on the first video" does the same without query pollution ─────────

@pytest.mark.asyncio
async def test_2_click_on_first_video_does_not_pollute_query(mock_orchestrator):
    orchestrator, registry, _ = mock_orchestrator
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    # First verify reference parsing doesn't extract "first video" as query
    parsed = parse_browser_reference("Click on the first video", ctx)
    assert parsed["item_type"] == "video"
    assert parsed["index"] == 1
    assert parsed["query"] != "first video"

    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=ElectroBOOM"

    organic_item = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0
    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=xyz123"
    title_link_first.text_content.return_value = "Fire Extinguisher vs High Voltage"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator(selector):
        if "ad" in selector:
            return ad_check
        if selector == "a#video-title":
            return title_link
        return AsyncMock()

    organic_item.locator.side_effect = item_locator

    renderers = AsyncMock()
    renderers.count.return_value = 1
    renderers.nth.return_value = organic_item

    def page_locator(selector):
        if selector == "ytd-video-renderer":
            return renderers
        return AsyncMock()

    mock_page.locator.side_effect = page_locator

    async def mock_wait_url(pred, timeout=None):
        mock_page.url = "https://www.youtube.com/watch?v=xyz123"

    mock_page.wait_for_url.side_effect = mock_wait_url

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        response = await orchestrator.process_input("Click on the first video")
        assert "Fire Extinguisher vs High Voltage" in response
        title_link_first.click.assert_called_once()


# ── 3. LLM returning "Task completed." without tool execution does not report success

@pytest.mark.asyncio
async def test_3_llm_hallucinating_task_completed_rejected(mock_orchestrator):
    orchestrator, _, _ = mock_orchestrator

    # Mock provider that falsely claims "Task completed." directly in text
    class FakeHallucinatingProvider(AIProvider):
        name = "fake"
        def is_available(self): return True
        def supports_vision(self): return False
        def supports_tools(self): return True
        def classify_intent(self, text):
            from app.ai.schemas import ClassifiedIntent, IntentType
            return ClassifiedIntent(type=IntentType.CONVERSATION, confidence=1.0, requires_cloud=False)
        async def respond(self, messages, tools=None, temperature=0.7, max_tokens=1024):
            return AIResponse(text="Task completed.", tool_calls=[])
        async def respond_stream(self, messages, tools=None, temperature=0.7):
            yield "Task completed."
        async def vision(self, prompt, images, tools=None):
            return AIResponse(text="")

    orchestrator.router = AIRouter(FakeHallucinatingProvider(), None)
    
    response = await orchestrator.process_input("Click on the first video")
    assert "Tool call required to perform this task" in response
    assert orchestrator._tools_executed_this_turn is False


# ── 4. Tool invocation with failed verification does not report completion ──────

@pytest.mark.asyncio
async def test_4_tool_invocation_with_failed_verification(mock_orchestrator):
    orchestrator, _, _ = mock_orchestrator
    ctx = get_browser_task_context()
    ctx.update_search("Firefox", "ElectroBOOM", "youtube", "https://www.youtube.com/results?search_query=ElectroBOOM")

    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=ElectroBOOM"

    organic_item = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0
    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=123"
    title_link_first.text_content.return_value = "Some Video"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator(selector):
        if "ad" in selector:
            return ad_check
        if selector == "a#video-title":
            return title_link
        return AsyncMock()

    organic_item.locator.side_effect = item_locator
    renderers = AsyncMock()
    renderers.count.return_value = 1
    renderers.nth.return_value = organic_item

    # Page url never changes (navigation fails)
    def page_locator(selector):
        if selector == "ytd-video-renderer":
            return renderers
        return AsyncMock()

    mock_page.locator.side_effect = page_locator

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        response = await orchestrator.process_input("Just click the first video")
        assert "verification_failed" in response or "could not verify" in response
        assert "Task completed." not in response
        assert orchestrator._tools_executed_this_turn is False


# ── 5. Genuine tool execution failure is surfaced correctly ─────────────────────

@pytest.mark.asyncio
async def test_5_genuine_tool_execution_failure_surfaced(mock_orchestrator):
    orchestrator, _, _ = mock_orchestrator
    # No active browser session
    with patch("app.tools.browser.inspection._get_active_page", return_value=None):
        response = await orchestrator.process_input("Just click the first video")
        assert "no_active_browser_session" in response or "No active Airi browser session" in response
        assert "Task completed." not in response


# ── 6. Correction referring to Firefox/current video does not route to launch_application

@pytest.mark.asyncio
async def test_6_correction_does_not_route_to_launch_application():
    cand1 = DesktopEntry(path="/path/vlc", name="VLC media player", exec="vlc", app_id="vlc")
    task = ApplicationClarificationTask(
        original_user_request="video",
        raw_transcribed_name="video",
        candidates=[cand1],
    )

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        # Correction mentioning browser/video abandons application launch
        res = await task.handle_input("No, click the first video in Firefox")
        assert task.is_complete is True
        assert task.clarification_stage == "ABANDONED"
        assert task.correction_instruction == "No, click the first video in Firefox"
        mock_launch.assert_not_called()


# ── 7. Missing or stale context does not launch an unrelated app ────────────────

@pytest.mark.asyncio
async def test_7_missing_or_stale_context_does_not_launch_unrelated_app(mock_orchestrator):
    orchestrator, _, _ = mock_orchestrator
    # Context is empty / cleared
    set_browser_task_context(BrowserTaskContext())

    with patch("app.tools.os_tools.apps.launch_application") as mock_launch_app, \
         patch("app.tools.browser.inspection._get_active_page", return_value=None):
        response = await orchestrator.process_input("Click on the first video")
        # Must route to browser tool (which fails due to no session), NEVER launch_application
        mock_launch_app.assert_not_called()
        assert "no_active_browser_session" in response or "No active Airi browser session" in response


# ── 8. BrowserTaskContext persists across consecutive voice turns ───────────────

@pytest.mark.asyncio
async def test_8_browser_task_context_persists_across_turns(mock_orchestrator):
    orchestrator, _, _ = mock_orchestrator
    ctx = get_browser_task_context()

    # Turn 1: Search performed
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )
    assert ctx.last_search_query == "ElectroBOOM"
    assert ctx.relevant_result_type == "video"

    mock_page = AsyncMock()
    mock_page.url = "https://www.youtube.com/results?search_query=ElectroBOOM"

    organic_item = AsyncMock()
    ad_check = AsyncMock()
    ad_check.count.return_value = 0
    title_link = AsyncMock()
    title_link.count.return_value = 1
    title_link_first = AsyncMock()
    title_link_first.is_visible.return_value = True
    title_link_first.get_attribute.return_value = "/watch?v=test12345"
    title_link_first.text_content.return_value = "Electric Shock Guitar"
    title_link_first.click = AsyncMock()
    title_link.first = title_link_first

    def item_locator(selector):
        if "ad" in selector:
            return ad_check
        if selector == "a#video-title":
            return title_link
        return AsyncMock()

    organic_item.locator.side_effect = item_locator
    renderers = AsyncMock()
    renderers.count.return_value = 1
    renderers.nth.return_value = organic_item

    def page_locator(selector):
        if selector == "ytd-video-renderer":
            return renderers
        return AsyncMock()

    mock_page.locator.side_effect = page_locator

    async def mock_wait_url(pred, timeout=None):
        mock_page.url = "https://www.youtube.com/watch?v=test12345"

    mock_page.wait_for_url.side_effect = mock_wait_url

    with patch("app.tools.browser.inspection._get_active_page", return_value=mock_page):
        # Turn 2: Click first video
        resp = await orchestrator.process_input("Just click the first video")
        assert "Electric Shock Guitar" in resp
        
        # Verify context updated with the navigated video
        assert ctx.current_url == "https://www.youtube.com/watch?v=test12345"
        assert ctx.current_title == "Electric Shock Guitar"
        assert ctx.last_search_query == "ElectroBOOM"
