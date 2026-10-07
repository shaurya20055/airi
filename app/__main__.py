"""Airi Desktop AI Assistant - Main Entry Point.

Supports multiple modes:
    python -m app              # Full application (voice + avatar)
    python -m app --cli        # CLI text chat mode
    python -m app --text       # Text-only mode (no voice)
    python -m app --diagnostics  # System diagnostics
    python -m app --list-tools   # List registered tools
"""
from __future__ import annotations

import argparse
import asyncio
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="airi",
        description="Airi — Your Personal Desktop AI Companion",
    )
    parser.add_argument("--text", action="store_true", help="Text-only mode (no voice)")
    parser.add_argument("--diagnostics", action="store_true", help="Run system diagnostics and exit")
    parser.add_argument("--list-tools", action="store_true", help="List all registered tools and exit")
    parser.add_argument("--test-audio", action="store_true", help="Test audio devices")
    parser.add_argument("--test-tts", action="store_true", help="Test TTS synthesis")
    parser.add_argument("--test-screen", action="store_true", help="Test screenshot capture")
    parser.add_argument("--test-browser", action="store_true", help="Test browser automation")
    parser.add_argument("--benchmark-models", action="store_true", help="Run local AI models benchmark")
    parser.add_argument("--cli", action="store_true", help="Interactive CLI chat mode")
    parser.add_argument("--no-avatar", action="store_true", help="Disable avatar overlay")
    parser.add_argument("--verbose", "-v", action="store_true", help="Set log level to DEBUG")
    return parser


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def run_diagnostics() -> None:
    """Run full system diagnostics and print results."""
    print("=" * 60)
    print("  Airi System Diagnostics")
    print("=" * 60)

    # OS
    print(f"\n{'OS:':<25} {platform.system()} {platform.release()}")
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    print(f"{'Distribution:':<25} {line.split('=', 1)[1].strip().strip('\"')}")
                    break
    except FileNotFoundError:
        pass

    # Python
    print(f"{'Python:':<25} {platform.python_version()} ({sys.executable})")

    # CPU
    print(f"{'CPU cores:':<25} {os.cpu_count()}")

    # RAM
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    print(f"{'RAM:':<25} {kb // 1024 // 1024 + 1} GB")
                    break
    except Exception:
        print(f"{'RAM:':<25} unknown")

    # GPU
    print()
    gpu_found = False
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    print(f"{'GPU (NVIDIA):':<25} {line.strip()}")
                    gpu_found = True
        except Exception:
            pass
    if shutil.which("lspci"):
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "VGA" in line or "3D" in line:
                    if not gpu_found:
                        print(f"{'GPU:':<25} {line.split(': ', 1)[-1]}")
        except Exception:
            pass
    if not gpu_found:
        print(f"{'GPU:':<25} not detected")

    # Display server
    print()
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    x11 = os.environ.get("DISPLAY", "")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    print(f"{'Display server:':<25} {session} (desktop: {desktop})")
    if wayland:
        print(f"{'Wayland display:':<25} {wayland}")
    if x11:
        print(f"{'X11 display:':<25} {x11}")

    # Audio
    print()
    if shutil.which("pactl"):
        try:
            r = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "Server Name" in line:
                    print(f"{'Audio server:':<25} {line.split(':', 1)[-1].strip()}")
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True, timeout=5,
            )
            sinks = [l for l in r.stdout.strip().splitlines() if l.strip()]
            print(f"{'Audio outputs:':<25} {len(sinks)} sink(s)")
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
            )
            sources = [l for l in r.stdout.strip().splitlines() if l.strip() and "monitor" not in l.lower()]
            print(f"{'Microphones:':<25} {len(sources)} source(s)")
        except Exception:
            pass
    else:
        print(f"{'Audio:':<25} pactl not found")

    # Brightness
    print()
    if shutil.which("brightnessctl"):
        try:
            r = subprocess.run(["brightnessctl", "info"], capture_output=True, text=True, timeout=5)
            for line in r.stdout.splitlines():
                if "Current" in line:
                    print(f"{'Brightness:':<25} {line.strip()}")
        except Exception:
            print(f"{'Brightness:':<25} brightnessctl available")
    else:
        print(f"{'Brightness:':<25} brightnessctl not found")

    # Screenshot
    if shutil.which("grim"):
        print(f"{'Screenshot tool:':<25} grim (Wayland)")
    elif shutil.which("scrot"):
        print(f"{'Screenshot tool:':<25} scrot (X11)")
    else:
        print(f"{'Screenshot tool:':<25} not found (install grim for Wayland)")

    # Browser
    print()
    for browser, name in [("firefox", "Firefox"), ("google-chrome-stable", "Chrome"), ("chromium", "Chromium")]:
        path = shutil.which(browser)
        if path:
            print(f"{'Browser:':<25} {name} ({path})")

    # STT
    print()
    try:
        import faster_whisper  # noqa: F401
        print(f"{'STT (faster-whisper):':<25} available")
    except ImportError:
        print(f"{'STT (faster-whisper):':<25} not installed (pip install faster-whisper)")

    # TTS
    try:
        import kokoro  # noqa: F401
        print(f"{'TTS (kokoro):':<25} available")
    except ImportError:
        print(f"{'TTS (kokoro):':<25} not installed (pip install kokoro)")

    # Wake word
    try:
        import openwakeword  # noqa: F401
        print(f"{'Wake word:':<25} available")
    except ImportError:
        print(f"{'Wake word:':<25} not installed (pip install openwakeword)")

    # OpenAI
    print()
    try:
        import openai  # noqa: F401
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            print(f"{'OpenAI:':<25} configured (key set)")
        else:
            print(f"{'OpenAI:':<25} library installed, no API key set")
    except ImportError:
        print(f"{'OpenAI:':<25} not installed (pip install openai)")

    # Playwright
    try:
        import playwright  # noqa: F401
        print(f"{'Playwright:':<25} installed")
    except ImportError:
        print(f"{'Playwright:':<25} not installed (pip install playwright)")

    # PySide6
    try:
        import PySide6  # noqa: F401
        print(f"{'PySide6 (UI):':<25} installed")
    except ImportError:
        print(f"{'PySide6 (UI):':<25} not installed (pip install pyside6)")

    print()
    print("=" * 60)
    print("  Diagnostics complete.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------

def run_list_tools() -> None:
    """List all registered tools with their details."""
    from app.tools.registry import ToolRegistry

    # Force import of all tool modules to trigger @tool decorator registration
    _import_all_tools()

    registry = ToolRegistry()
    tools = registry.list_tools()

    if not tools:
        print("No tools registered.")
        return

    print(f"\n{'='*60}")
    print(f"  Registered Tools ({len(tools)})")
    print(f"{'='*60}\n")

    categories: dict[str, list] = {}
    for t in tools:
        categories.setdefault(t.category, []).append(t)

    for cat in sorted(categories):
        print(f"  [{cat}]")
        for t in sorted(categories[cat], key=lambda x: x.name):
            perm_icon = {"safe": "✓", "confirm": "⚠", "dangerous": "✗", "blocked": "⊘"}.get(
                t.permission_level.value, "?"
            )
            params = ", ".join(p.name for p in t.parameters) if t.parameters else ""
            print(f"    {perm_icon} {t.name}({params}) — {t.description}")
        print()


def _import_all_tools() -> None:
    """Import all tool modules to trigger decorator-based registration."""
    tool_modules = [
        "app.tools.os_tools.volume",
        "app.tools.os_tools.brightness",
        "app.tools.os_tools.apps",
        "app.tools.system.power",
        "app.tools.system.info",
        "app.tools.screen.capture",
        "app.tools.files.manager",
    ]
    import importlib
    for mod in tool_modules:
        try:
            importlib.import_module(mod)
        except ImportError as e:
            print(f"  Warning: could not import {mod}: {e}")


# ---------------------------------------------------------------------------
# CLI chat mode
# ---------------------------------------------------------------------------

def run_cli_chat(verbose: bool = False) -> None:
    """Run the interactive CLI chat loop with the full agent stack."""
    asyncio.run(_async_cli_chat(verbose))


async def _async_cli_chat(verbose: bool = False) -> None:
    """Async CLI chat loop."""
    from app.core.logging.logger import setup_logging
    from app.core.events.bus import EventBus
    from app.core.permissions.manager import PermissionManager, PermissionLevel
    from app.tools.registry import ToolRegistry
    from app.ai.providers.local.provider import LocalProvider
    from app.ai.router import AIRouter
    from app.memory.store import MemoryStore
    from app.agent.orchestrator import AgentOrchestrator

    # Setup
    setup_logging(log_level="DEBUG" if verbose else "INFO", pretty_console=True)
    _import_all_tools()

    event_bus = EventBus()
    registry = ToolRegistry()
    permission_manager = PermissionManager(event_bus, cli_mode=True)

    # Memory
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    memory = MemoryStore(str(data_dir / "memory.db"))
    await memory.initialize()

    # AI
    from app.core.config.settings import get_settings
    settings = get_settings()
    
    local_runtime = None
    if settings.local_ai_enabled and settings.local_ai_runtime == "ollama":
        from app.ai.providers.local.ollama_runtime import OllamaRuntime
        local_runtime = OllamaRuntime(model=settings.local_ai_model, timeout=settings.local_ai_timeout)
        if await local_runtime._check_server():
            print(f"  🧠 Local AI ({settings.local_ai_model}) connected.")
        else:
            print("  ⚠  Local AI server not reachable (Ollama not running).")
            
    local_provider = LocalProvider(runtime=local_runtime)

    # Try to set up cloud provider
    cloud_provider = None
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        try:
            from app.ai.providers.openai_provider.provider import OpenAIProvider
            cloud_provider = OpenAIProvider(api_key=api_key)
            if cloud_provider.is_available():
                print("  ☁  Cloud AI provider connected.")
        except Exception:
            cloud_provider = None

    router = AIRouter(local_provider, cloud_provider)
    orchestrator = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=permission_manager,
    )

    # Welcome
    print()
    print("╔══════════════════════════════════════════╗")
    print("║       Airi — Desktop AI Assistant        ║")
    print("║  Type commands or questions. 'exit' quit  ║")
    print("╚══════════════════════════════════════════╝")
    if not cloud_provider:
        print("  ℹ  Running in local-only mode (no cloud AI)")
    print()

    while True:
        try:
            user_input = input("[You] ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("\n[Airi] Goodbye! ✨")
            break

        try:
            response = await orchestrator.process_input(user_input, source="cli")
            print(f"\n[Airi] {response}\n")
        except Exception as e:
            print(f"\n[Airi] Sorry, something went wrong: {e}\n")

    await memory.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    parser = get_parser()
    args = parser.parse_args()

    if args.diagnostics:
        run_diagnostics()
        sys.exit(0)

    if args.list_tools:
        run_list_tools()
        sys.exit(0)

    if args.cli or args.text:
        run_cli_chat(verbose=args.verbose)
        sys.exit(0)

    if args.test_audio:
        print("Audio test — Phase 2 (voice pipeline)")
        print("Install: pip install sounddevice")
        try:
            import sounddevice as sd
            print(f"\nInput devices:\n{sd.query_devices(kind='input')}")
            print(f"\nOutput devices:\n{sd.query_devices(kind='output')}")
        except ImportError:
            print("sounddevice not installed.")
        except Exception as e:
            print(f"Error: {e}")
        sys.exit(0)

    if args.test_tts:
        print("TTS test — Phase 2 (voice pipeline)")
        try:
            from app.voice.tts.kokoro_provider import KokoroTTSProvider
            provider = KokoroTTSProvider()
            if provider.is_available():
                print("Kokoro TTS is available. Run voice pipeline for full test.")
            else:
                print("Kokoro TTS not available. Install: pip install kokoro")
        except Exception as e:
            print(f"TTS test error: {e}")
        sys.exit(0)

    if args.test_screen:
        print("Screenshot test — Phase 4 (computer control)")
        asyncio.run(_test_screenshot())
        sys.exit(0)

    if args.test_browser:
        print("Browser test — Phase 4 (browser automation)")
        print("Not yet implemented.")
        sys.exit(0)

    if args.benchmark_models:
        from app.benchmark import run_benchmark
        asyncio.run(run_benchmark())
        sys.exit(0)

    # Default: full application (Phase 3+)
    print("Full application mode (avatar + voice) is Phase 3+.")
    print("Use --cli for the interactive command line interface.")
    print("Use --diagnostics to check your system.")


async def _test_screenshot() -> None:
    """Test screenshot capture."""
    from app.tools.screen.capture import take_screenshot
    result = await take_screenshot()
    if result.success:
        print(f"Screenshot saved: {result.data}")
    else:
        print(f"Screenshot failed: {result.error}")


if __name__ == "__main__":
    main()
