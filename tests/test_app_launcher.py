from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.tools.os_tools.desktop_parser import DesktopEntry
from app.tools.os_tools.app_resolver import AppResolver
from app.tools.os_tools.apps import launch_application, launch_desktop_entry, set_resolver
from app.core.events.bus import EventBus
from app.core.permissions.manager import PermissionManager, PermissionLevel
from app.memory.store import MemoryStore
from app.agent.orchestrator import AgentOrchestrator
from app.ai.providers.local.provider import LocalProvider
from app.ai.router import AIRouter
from app.tools.registry import ToolRegistry


@pytest.fixture
def mock_resolver():
    resolver = AppResolver()
    resolver.entries = [
        DesktopEntry(path="/usr/share/applications/firefox.desktop", name="Firefox", exec="firefox %u", keywords=["browser", "web", "internet"], app_id="firefox"),
        DesktopEntry(path="/usr/share/applications/google-chrome.desktop", name="Google Chrome", exec="google-chrome-stable %U", keywords=["browser", "web"], app_id="google-chrome"),
        DesktopEntry(path="/usr/share/applications/helium.desktop", name="Helium", exec="helium-browser", keywords=["browser", "lightweight"], app_id="helium"),
        DesktopEntry(path="/usr/share/applications/vlc.desktop", name="VLC media player", exec="vlc %U", keywords=["video", "audio", "player"], app_id="vlc"),
        DesktopEntry(path="/usr/share/applications/code.desktop", name="Visual Studio Code", exec="code", keywords=["editor", "ide"], app_id="code"),
        DesktopEntry(path="/usr/share/applications/code-insiders.desktop", name="Visual Studio Code Insiders", exec="code-insiders", keywords=["editor", "ide"], app_id="code-insiders"),
        DesktopEntry(path="/usr/share/applications/burp-suite.desktop", name="Burp Suite", exec="burpsuite", keywords=["security", "pentest", "proxy"], app_id="burp-suite"),
    ]
    resolver._initialized = True
    return resolver


# ── Test A: Exact Resolution ──────────────────────────────────────────────────

def test_exact_name(mock_resolver):
    match = mock_resolver.resolve("Firefox")
    assert match.entry is not None
    assert match.entry.name == "Firefox"
    assert match.is_ambiguous is False
    assert match.requires_clarification is False


def test_exact_burp_suite(mock_resolver):
    """A: Exact 'Burp Suite' request resolves to the installed Burp Suite entry without clarification."""
    match = mock_resolver.resolve("Burp Suite")
    assert match.entry is not None
    assert match.entry.name == "Burp Suite"
    assert match.requires_clarification is False
    assert match.confidence == 1.0


# ── Test B: Candidate Clarification for Speech Errors ─────────────────────────

def test_burpshoot_candidate(mock_resolver):
    """B: 'Burpshoot' finds Burp Suite as a plausible candidate and requests confirmation."""
    match = mock_resolver.resolve("Burpshoot")
    assert match.requires_clarification is True
    assert len(match.candidates) >= 1
    assert match.candidates[0].name == "Burp Suite"
    assert "Burp Suite" in match.clarification_prompt
    assert "Burpshoot" in match.clarification_prompt


def test_burp_sweet_candidate(mock_resolver):
    """'Burp sweet' finds Burp Suite as a plausible candidate and requests confirmation."""
    match = mock_resolver.resolve("Burp sweet")
    assert match.requires_clarification is True
    assert len(match.candidates) >= 1
    assert match.candidates[0].name == "Burp Suite"


def test_firebox_candidate(mock_resolver):
    """'Firebox' finds Firefox as a candidate via Soundex/edit distance."""
    match = mock_resolver.resolve("Firebox")
    assert match.requires_clarification is True
    assert len(match.candidates) >= 1
    assert match.candidates[0].name == "Firefox"


# ── Test C, D, E, J: End-to-End Orchestrator Confirmation Workflow ─────────────

@pytest.fixture
async def orchestrator_setup(mock_resolver, tmp_path):
    set_resolver(mock_resolver)
    import app.tools.os_tools.apps
    from app.tools import register_all_tools
    register_all_tools(ToolRegistry())
    registry = ToolRegistry()

    event_bus = EventBus()
    perm_manager = PermissionManager(event_bus, cli_mode=True)
    memory = MemoryStore(str(tmp_path / "memory.db"))
    await memory.initialize()

    local_provider = LocalProvider()
    router = AIRouter(local_provider, None)

    orchestrator = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=perm_manager,
    )
    yield orchestrator, mock_resolver
    await memory.close()


@pytest.mark.asyncio
async def test_yes_launches_exact_candidate(orchestrator_setup):
    """C: 'Yes' on the next turn launches the exact previously selected Burp Suite candidate."""
    orchestrator, resolver = orchestrator_setup

    with patch("app.tools.os_tools.apps.launch_desktop_entry", new_callable=AsyncMock) as mock_launch:
        mock_launch.return_value = (True, "Launched Burp Suite.")

        # Turn 1: User says "Open Burpshoot."
        r1 = await orchestrator.process_input("Open Burpshoot.")
        assert "Burp Suite" in r1
        assert "Did you mean that?" in r1 or "Burp Suite" in r1
        assert orchestrator.pending_task is not None
        mock_launch.assert_not_called()

        # Turn 2: User says "Yes."
        r2 = await orchestrator.process_input("Yes.")
        assert "Launched Burp Suite" in r2
        assert orchestrator.pending_task is None
        mock_launch.assert_called_once()
        called_entry = mock_launch.call_args[0][0]
        assert called_entry.name == "Burp Suite"


@pytest.mark.asyncio
async def test_no_never_launches_candidate(orchestrator_setup):
    """D: 'No' cancels the clarification and never launches the candidate."""
    orchestrator, resolver = orchestrator_setup

    with patch("app.tools.os_tools.apps.launch_desktop_entry", new_callable=AsyncMock) as mock_launch:
        # Turn 1: User says "Open Burpshoot."
        r1 = await orchestrator.process_input("Open Burpshoot.")
        assert "Burp Suite" in r1
        assert orchestrator.pending_task is not None

        # Turn 2: User says "No."
        r2 = await orchestrator.process_input("No.")
        assert "won't launch Burp Suite" in r2 or "cancelled" in r2.lower()
        assert orchestrator.pending_task is None
        mock_launch.assert_not_called()


@pytest.mark.asyncio
async def test_isolated_yes_does_not_launch(orchestrator_setup):
    """E: 'Yes' without a pending clarification does not launch an application."""
    orchestrator, _ = orchestrator_setup

    with patch("app.tools.os_tools.apps.launch_desktop_entry", new_callable=AsyncMock) as mock_launch:
        resp = await orchestrator.process_input("Yes.")
        mock_launch.assert_not_called()
        assert "Launched" not in resp


@pytest.mark.asyncio
async def test_clarification_survives_multiple_turns(orchestrator_setup):
    """J: Clarification state survives multiple interactive push-to-talk turns."""
    orchestrator, _ = orchestrator_setup

    with patch("app.tools.os_tools.apps.launch_desktop_entry", new_callable=AsyncMock) as mock_launch:
        mock_launch.return_value = (True, "Launched Burp Suite.")

        # Turn 1: Start clarification
        r1 = await orchestrator.process_input("Open Burpshoot.")
        assert "Burp Suite" in r1

        # Turn 2: User says something ambiguous
        r2 = await orchestrator.process_input("Wait, what does that do?")
        assert "Please answer 'yes'" in r2
        assert orchestrator.pending_task is not None
        mock_launch.assert_not_called()

        # Turn 3: User confirms
        r3 = await orchestrator.process_input("Yeah, open it.")
        assert "Launched Burp Suite" in r3
        assert orchestrator.pending_task is None
        mock_launch.assert_called_once()


@pytest.mark.asyncio
async def test_candidate_confirmation_does_not_grant_unrelated_permissions(orchestrator_setup):
    """K: Candidate confirmation does not grant unrelated permissions or session overrides."""
    orchestrator, _ = orchestrator_setup

    with patch("app.tools.os_tools.apps.launch_desktop_entry", new_callable=AsyncMock) as mock_launch:
        mock_launch.return_value = (True, "Launched Burp Suite.")
        await orchestrator.process_input("Open Burpshoot.")
        await orchestrator.process_input("Yes.")

        # Verify shutdown / dangerous commands are NOT auto-granted
        assert not orchestrator.permission_manager.check_permission("shutdown", PermissionLevel.DANGEROUS)


# ── Test F, G, H, I: Ambiguity, Failures, and Regressions ──────────────────────

def test_ambiguous_request_presents_candidates(mock_resolver):
    """F: An ambiguous request presents candidates rather than choosing arbitrarily."""
    match = mock_resolver.resolve("Web Browser")
    assert match.is_ambiguous is True
    assert "Firefox" in match.ambiguous_candidates
    assert "Google Chrome" in match.ambiguous_candidates
    assert match.entry is None


def test_nonexistent_application_reported_honestly(mock_resolver):
    """G: A nonexistent application with no credible candidates is reported honestly."""
    match = mock_resolver.resolve("launch completelyfakeappthatdoesntexist")
    assert match.entry is None
    assert match.is_ambiguous is False
    assert match.requires_clarification is False
    assert match.method == "not_found"


@pytest.mark.asyncio
async def test_candidate_missing_executable_fails():
    """H: A candidate whose executable does not exist is not reported as successfully launched."""
    fake_entry = DesktopEntry(
        path="/tmp/fake.desktop",
        name="Missing Tool",
        exec="/usr/bin/completely_nonexistent_binary_xyz_98765",
    )
    success, message = await launch_desktop_entry(fake_entry)
    assert success is False
    assert "was not found on this system" in message or "executable" in message.lower()


def test_helium_regression_never_falls_back_to_firefox(mock_resolver):
    """I: 'helm browser' can suggest Helium but never silently falls back to Firefox."""
    match = mock_resolver.resolve("helm browser")
    assert match.entry is not None or len(match.candidates) > 0
    resolved_name = match.entry.name if match.entry else match.candidates[0].name
    assert resolved_name == "Helium"
    assert resolved_name != "Firefox"


# ── Natural Language Variants ─────────────────────────────────────────────────

def test_natural_language_variants(mock_resolver):
    match = mock_resolver.resolve("open firefox browser")
    assert match.entry is not None
    assert match.entry.name == "Firefox"

    match = mock_resolver.resolve("launch Google Chrome")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"

    match = mock_resolver.resolve("start chrome browser")
    assert match.entry is not None
    assert match.entry.name == "Google Chrome"


def test_category_only_clarification(mock_resolver):
    match = mock_resolver.resolve("open browser")
    assert match.is_ambiguous is True
    assert match.entry is None
    
    match = mock_resolver.resolve("open a browser")
    assert match.is_ambiguous is True
    assert match.entry is None
