"""Comprehensive regression suite for browser contextual references and confirmation handling.

Addresses failure log scenarios:
- browser_search("ElectroBOOM", site="youtube") followed by "Open the first video that comes in the result"
- AppResolver receiving descriptive phrases and rejecting them
- Clarification task for VLC being abandoned on correction and routing to browser tool
- Cancellation with "No, the browser"
- Strict candidate selection with "1" / "first one"
- Pronoun resolution: "Play it"
- BROWSER_CONTROL policy permission verification (SAFE)
- End-to-end simulated session
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
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.core.events.bus import EventBus
from app.core.permissions.browser_policy import BrowserPolicy
from app.core.permissions.levels import PermissionLevel
from app.core.permissions.manager import PermissionManager
from app.memory.store import MemoryStore
from app.tools.os_tools.app_resolver import AppResolver
from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.registry import ToolDefinition, ToolParameter, ToolRegistry, ToolResult


@pytest.fixture(autouse=True)
def reset_browser_context():
    """Reset the browser task context before and after each test."""
    ctx = BrowserTaskContext()
    set_browser_task_context(ctx)
    yield ctx
    set_browser_task_context(BrowserTaskContext())


@pytest.fixture
def mock_vlc_resolver():
    resolver = AppResolver()
    resolver.entries = [
        DesktopEntry(
            path="/usr/share/applications/vlc.desktop",
            name="VLC media player",
            exec="vlc %U",
            keywords=["video", "audio", "player"],
            app_id="vlc",
        ),
        DesktopEntry(
            path="/usr/share/applications/firefox.desktop",
            name="Firefox",
            exec="firefox %u",
            keywords=["browser", "web"],
            app_id="firefox",
        ),
    ]
    resolver._initialized = True
    return resolver


# ── Test A: Contextual Routing to Browser Tool Instead of App Launch ─────────

def test_a_intent_routes_to_browser_tool_not_app_launch():
    """A. browser_search followed by 'Open the first video that comes in the result'
    must route to browser_select_first, NOT launch_application.
    """
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    provider = LocalProvider()
    utterance = "Open the first video that comes in the result"
    intent = provider.classify_intent(utterance)

    assert intent.tool_name == "browser_select_first"
    assert intent.tool_name != "launch_application"
    assert intent.tool_args.get("item_type") == "video"
    assert intent.tool_args.get("index") == 1
    assert intent.tool_args.get("query") == "ElectroBOOM"


# ── Test B: AppResolver Rejects Descriptive Result Phrases ───────────────────

def test_b_app_resolver_rejects_descriptive_result_phrases(mock_vlc_resolver):
    """B. Verify AppResolver never treats descriptive phrases as applications."""
    descriptive_inputs = [
        "the first video that comes in the result",
        "Open the first video that comes in the result",
        "first video",
        "the first video",
        "the second video",
        "Click the first search result",
        "Select the first option",
    ]

    for query in descriptive_inputs:
        result = mock_vlc_resolver.resolve(query)
        assert result.entry is None, f"Expected None for '{query}', but got {result.entry}"
        assert result.method == "descriptive_reference" or not result.requires_clarification
        assert result.requires_clarification is False
        assert len(result.candidates) == 0


# ── Test C: 'Open the first video' with Active YouTube Context ────────────────

def test_c_open_first_video_with_active_youtube_context():
    """C. Utterance: 'Open the first video' with active YouTube context resolves to video selection."""
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    provider = LocalProvider()
    intent = provider.classify_intent("Open the first video")
    assert intent.tool_name == "browser_select_first"
    assert intent.tool_args["item_type"] == "video"
    assert intent.tool_args["index"] == 1
    assert intent.tool_args["query"] == "ElectroBOOM"


# ── Test D: 'Open the second video' Resolves to Index 2 ───────────────────────

def test_d_open_second_video_resolves_to_index_2():
    """D. Utterance: 'Open the second video' resolves to index 2."""
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    provider = LocalProvider()
    intent = provider.classify_intent("Open the second video")
    assert intent.tool_name == "browser_select_first"
    assert intent.tool_args["index"] == 2
    assert intent.tool_args["item_type"] == "video"


# ── Test E: 'Click the first search result' with Active Web Search ───────────

def test_e_click_first_search_result_resolves_to_result():
    """E. Utterance: 'Click the first search result' with active web search resolves to result selection."""
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="Python documentation",
        site="google",
        url="https://www.google.com/search?q=Python+documentation",
    )

    provider = LocalProvider()
    intent = provider.classify_intent("Click the first search result")
    assert intent.tool_name == "browser_select_first"
    assert intent.tool_args["item_type"] == "result"
    assert intent.tool_args["index"] == 1


# ── Test F: Clarification Task Abandoned on Correction Without Launching VLC ──

@pytest.mark.asyncio
async def test_f_clarification_task_abandoned_on_correction_routes_to_browser(tmp_path):
    """F. Clarification task active for [Candidate 1: VLC]:
    User says: 'Firefox that we just opened. First video that comes on the ElectroBoom page.'
    -> Must NOT launch VLC.
    -> Must abandon clarification and route to browser tool.
    """
    event_bus = EventBus()
    pm = PermissionManager(event_bus, cli_mode=False)
    registry = ToolRegistry()
    registry._tools.clear()

    browser_select_mock = AsyncMock(return_value=ToolResult(success=True, message="Opened video: ElectroBOOM"))
    registry.register(
        ToolDefinition(
            name="browser_select_first",
            description="Select first item",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="item_type", type="string", description="Item type", default="video", required=False),
                ToolParameter(name="query", type="string", description="Query", default="", required=False),
                ToolParameter(name="index", type="integer", description="Index", default=1, required=False),
            ],
        ),
        browser_select_mock,
    )

    memory = MemoryStore(str(tmp_path / "f.db"))
    await memory.initialize()

    local_provider = LocalProvider()
    router = AIRouter(local_provider=local_provider)
    orch = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=pm,
    )

    # Setup active browser context
    ctx = get_browser_task_context()
    ctx.update_search("Firefox", "ElectroBOOM", "youtube", "https://youtube.com/results?search_query=ElectroBOOM")

    # Manually attach a clarification task presenting VLC
    vlc_cand = DesktopEntry(
        path="/usr/share/applications/vlc.desktop",
        name="VLC media player",
        exec="vlc",
        app_id="vlc",
    )
    task = ApplicationClarificationTask(
        original_user_request="the first video that comes in the result",
        raw_transcribed_name="the first video that comes in the result",
        candidates=[vlc_cand],
    )
    orch.pending_task = task

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        mock_launch.return_value = (True, "Launched VLC")
        response = await orch.process_input(
            "Firefox that we just opened. First video that comes on the ElectroBoom page."
        )

        # VLC must NEVER have been launched
        mock_launch.assert_not_called()

        # Browser tool must have been executed
        browser_select_mock.assert_called_once()
        args = browser_select_mock.call_args[0][0] if browser_select_mock.call_args[0] else browser_select_mock.call_args[1]
        assert args.get("index") == 1
        assert "ElectroBoom" in args.get("query", "") or args.get("item_type") == "video"

    await memory.close()


# ── Test G: Clarification Cancellation with 'No, the browser' ─────────────────

@pytest.mark.asyncio
async def test_g_clarification_task_cancelled_cleanly():
    """G. Clarification task active:
    User says: 'No, the browser'
    -> Must cancel cleanly, no app launched.
    """
    vlc_cand = DesktopEntry(
        path="/usr/share/applications/vlc.desktop",
        name="VLC media player",
        exec="vlc",
        app_id="vlc",
    )
    task = ApplicationClarificationTask(
        original_user_request="the first video",
        raw_transcribed_name="the first video",
        candidates=[vlc_cand],
    )

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        response = await task.handle_input("No, the browser")
        assert task.is_complete is True
        assert task.clarification_stage == "CANCELLED"
        assert task.correction_instruction is None
        mock_launch.assert_not_called()
        assert "won't launch" in response or "cancelled" in response.lower()


# ── Test H: Strict Candidate Selection with '1' and 'first one' ───────────────

@pytest.mark.asyncio
async def test_h_strict_candidate_selection():
    """H. Clarification task active:
    User says: '1' or 'first one'
    -> Selects candidate 1 only when clearly intended as selection.
    """
    cand1 = DesktopEntry(path="/path/1", name="App One", exec="app1", app_id="app1")
    cand2 = DesktopEntry(path="/path/2", name="App Two", exec="app2", app_id="app2")

    task = ApplicationClarificationTask(
        original_user_request="app",
        raw_transcribed_name="app",
        candidates=[cand1, cand2],
    )

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        mock_launch.return_value = (True, "Launched App One")

        # "1" selects candidate 1
        resp = await task.handle_input("1")
        assert task.is_complete is True
        assert task.selected_candidate == cand1
        mock_launch.assert_called_once_with(cand1)

    # Test "first one"
    task2 = ApplicationClarificationTask(
        original_user_request="app",
        raw_transcribed_name="app",
        candidates=[cand1, cand2],
    )
    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        mock_launch.return_value = (True, "Launched App One")
        resp = await task2.handle_input("first one")
        assert task2.is_complete is True
        assert task2.selected_candidate == cand1
        mock_launch.assert_called_once_with(cand1)


# ── Test I: Pronoun Resolution ('Play it') ────────────────────────────────────

def test_i_pronoun_resolution_play_it():
    """I. Pronoun resolution:
    'Search YouTube for ElectroBOOM'
    Follow-up: 'Play it'
    -> Routes to playing the first video result.
    """
    ctx = get_browser_task_context()
    ctx.update_search(
        browser_name="Firefox",
        query="ElectroBOOM",
        site="youtube",
        url="https://www.youtube.com/results?search_query=ElectroBOOM",
    )

    provider = LocalProvider()
    intent = provider.classify_intent("Play it")

    assert intent.tool_name == "browser_select_first"
    assert intent.tool_args["item_type"] == "video"
    assert intent.tool_args["index"] == 1
    assert intent.tool_args["query"] == "ElectroBOOM"


# ── Test J: Permission Policy BROWSER_CONTROL is SAFE ─────────────────────────

def test_j_browser_search_permission_policy_is_safe():
    """J. Permission test:
    'open firefox and search youtube for ElectroBOOM'
    -> SAFE execution under BROWSER_CONTROL policy without confirmation prompt.
    """
    level, reason = BrowserPolicy.classify(
        "browser_search",
        {"browser_name": "Firefox", "query": "ElectroBOOM", "site": "youtube"},
    )
    assert level == PermissionLevel.SAFE
    assert reason == ""

    # Sensitive operations are escalated
    level_sens, reason_sens = BrowserPolicy.classify(
        "browser_click",
        {"selector": "button#checkout-payment-confirm"},
    )
    assert level_sens == PermissionLevel.CONFIRM
    assert "sensitive" in reason_sens.lower()


# ── Test K: End-to-End Simulated Session Matching Real Failure Log ───────────

@pytest.mark.asyncio
async def test_k_end_to_end_simulated_session_matches_failure_log(tmp_path):
    """K. End-to-end simulated session matching the real failure log:
    1. 'open firefox and search youtube for electroboom'
       -> executes browser_search
    2. 'open the first video that comes in the result'
       -> executes browser selection/click, plays video
       -> never prompts for VLC or desktop app launch.
    """
    event_bus = EventBus()
    pm = PermissionManager(event_bus, cli_mode=False)
    registry = ToolRegistry()
    registry._tools.clear()

    browser_search_mock = AsyncMock(
        return_value=ToolResult(
            success=True,
            message="Searched for 'electroboom' on youtube",
            data={"browser": "Firefox", "url": "https://www.youtube.com/results?search_query=electroboom"},
        )
    )
    browser_select_mock = AsyncMock(
        return_value=ToolResult(
            success=True,
            message="Opened video: 'ElectroBOOM - How Safe Is AC vs DC?'",
            data={"verified": True, "url": "https://www.youtube.com/watch?v=123"},
        )
    )

    registry.register(
        ToolDefinition(
            name="browser_search",
            description="Browser search",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="browser_name", type="string", description="Browser name", default="Firefox", required=False),
                ToolParameter(name="query", type="string", description="Query", required=True),
                ToolParameter(name="site", type="string", description="Site", default="youtube", required=False),
            ],
        ),
        browser_search_mock,
    )
    registry.register(
        ToolDefinition(
            name="browser_select_first",
            description="Browser select",
            category="browser",
            permission_level=PermissionLevel.SAFE,
            parameters=[
                ToolParameter(name="item_type", type="string", description="Item type", default="video", required=False),
                ToolParameter(name="query", type="string", description="Query", default="", required=False),
                ToolParameter(name="index", type="integer", description="Index", default=1, required=False),
            ],
        ),
        browser_select_mock,
    )

    memory = MemoryStore(str(tmp_path / "k.db"))
    await memory.initialize()

    local_provider = LocalProvider()
    router = AIRouter(local_provider=local_provider)
    orch = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=pm,
    )

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_app_launch, \
         patch("app.tools.os_tools.app_resolver.AppResolver.resolve") as mock_resolver:

        # Step 1: User says "open firefox and search youtube for electroboom"
        resp1 = await orch.process_input("open firefox and search youtube for electroboom")
        assert "browser_search succeeded" in resp1 or "Searched" in resp1

        # Simulate context update performed by _do_browser_search
        get_browser_task_context().update_search(
            browser_name="Firefox",
            query="electroboom",
            site="youtube",
            url="https://www.youtube.com/results?search_query=electroboom",
        )

        # Step 2: User says "open the first video that comes in the result"
        resp2 = await orch.process_input("open the first video that comes in the result")
        assert "browser_select_first succeeded" in resp2 or "Opened video" in resp2

        # Verification: Desktop app launching or AppResolver must NEVER be touched
        mock_app_launch.assert_not_called()
        mock_resolver.assert_not_called()
        assert orch.pending_task is None

    await memory.close()


# ── Test L: Isolated 'yes' Without Confirmation Never Launches App ────────────

@pytest.mark.asyncio
async def test_l_isolated_yes_never_launches_application(tmp_path):
    """L. An isolated 'yes' without a pending confirmation must never launch an application."""
    event_bus = EventBus()
    pm = PermissionManager(event_bus, cli_mode=False)
    registry = ToolRegistry()
    registry._tools.clear()

    memory = MemoryStore(str(tmp_path / "l.db"))
    await memory.initialize()

    local_provider = LocalProvider()
    router = AIRouter(local_provider=local_provider)
    orch = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=pm,
    )

    with patch("app.tools.os_tools.apps.launch_desktop_entry") as mock_launch:
        response = await orch.process_input("yes")
        mock_launch.assert_not_called()
        assert orch.pending_task is None
        assert "launch" not in response.lower() or "can't handle" in response.lower()

    await memory.close()
