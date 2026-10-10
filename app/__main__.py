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
    parser.add_argument("--test-stt", action="store_true", help="Test Speech-to-Text (STT) transcription")
    parser.add_argument("--audio-file", type=str, default="", help="Audio file path for --test-stt")
    parser.add_argument("--benchmark-stt", action="store_true", help="Run STT benchmark on candidate models and samples")
    parser.add_argument("--reference-text", type=str, default="", help="Reference transcript for WER evaluation")
    parser.add_argument("--samples-dir", type=str, default="", help="Directory of WAV samples for STT benchmark")
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
        "app.tools.system.terminal",
        "app.tools.system.gpu",
        "app.tools.system.network",
        "app.tools.system.visible_terminal",
        "app.tools.browser.automation",
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
        print("Voice Pipeline Test (Push-to-Talk)")
        asyncio.run(_run_voice_pipeline(verbose=args.verbose))
        sys.exit(0)

    if args.test_stt:
        asyncio.run(_test_stt(audio_file=args.audio_file, verbose=args.verbose))
        sys.exit(0)

    if args.benchmark_stt:
        asyncio.run(_run_stt_benchmark_cli(
            audio_file=args.audio_file,
            samples_dir=args.samples_dir,
            reference_text=args.reference_text,
        ))
        sys.exit(0)

    if args.test_tts:
        print("TTS test — Synthesizing test phrase...")
        asyncio.run(_test_tts())
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


async def _test_stt(audio_file: str = "", verbose: bool = False) -> None:
    """Test Speech-to-Text (STT) transcription and report metrics."""
    from app.core.config.settings import get_settings
    from app.voice.stt.whisper_provider import WhisperSTTProvider

    settings = get_settings()
    print("=" * 60)
    print("  Airi Speech-to-Text (STT) Test")
    print("=" * 60)
    print(f"Loading STT Model: {settings.stt_model} (device: {settings.stt_device}, compute: {settings.stt_compute_type})...")

    stt = WhisperSTTProvider()
    if not stt.is_available():
        print("Error: Faster Whisper is not available. Please install dependencies.")
        return

    import numpy as np
    import time
    from pathlib import Path

    sample_rate = 16000
    audio_data = None

    if audio_file and Path(audio_file).exists():
        print(f"\n📁 Transcribing audio file: {audio_file}")
        result = await stt.transcribe_file(audio_file)
    else:
        import sounddevice as sd
        frames = []

        def callback(indata, frames_count, time_info, status):
            if status and verbose:
                print(f"Status: {status}")
            frames.append(indata.copy())

        def wait_for_enter():
            input("🎙️ Recording... Press Enter to stop.")

        if sys.stdin.isatty():
            print("\n🎤 Press Enter to start recording your utterance...")
            try:
                input()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return

            try:
                with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32", callback=callback):
                    await asyncio.to_thread(wait_for_enter)
            except Exception as e:
                print(f"Error opening audio input device: {e}")
                return
        else:
            print("Non-interactive session detected without audio file. Synthesizing test utterance via TTS...")
            from app.voice.tts.kokoro_provider import KokoroTTSProvider
            tts = KokoroTTSProvider(voice_id=settings.tts_voice)
            if tts.is_available():
                import io, soundfile as sf
                tts_res = await tts.synthesize("Open Firefox and search YouTube.")
                with io.BytesIO(tts_res.audio_data) as f:
                    audio_data, sample_rate = sf.read(f)
            else:
                audio_data = np.zeros(sample_rate * 2, dtype=np.float32)

        if audio_data is None:
            if not frames:
                print("No audio recorded.")
                return
            audio_data = np.concatenate(frames, axis=0)
            audio_data = np.squeeze(audio_data)

        print("⚙️ Transcribing utterance...")
        result = await stt.transcribe(audio_data, sample_rate=sample_rate)

    print("\n" + "=" * 60)
    print("  STT Report")
    print("=" * 60)
    print(f"{'Model:':<25} {result.metrics.get('model_size', stt.model_size)} (device: {result.metrics.get('device', stt.device)}, compute: {result.metrics.get('compute_type', stt.compute_type)})")
    print(f"{'Language:':<25} {result.language} (confidence: {result.confidence:.2%})")
    print(f"{'Transcript:':<25} {result.text!r}")
    print(f"{'STT Latency:':<25} {result.latency:.3f}s")
    if 'audio_duration_sec' in result.metrics:
        print(f"{'Audio Duration:':<25} {result.metrics['audio_duration_sec']:.2f}s")
    if 'real_time_factor' in result.metrics:
        print(f"{'Real-Time Factor:':<25} {result.metrics['real_time_factor']:.3f}x")
    if 'segments_count' in result.metrics:
        print(f"{'Segments Count:':<25} {result.metrics['segments_count']}")
    if result.segments:
        for idx, seg in enumerate(result.segments, 1):
            start = seg.get('start', 0.0)
            end = seg.get('end', 0.0)
            seg_text = seg.get('text', '').strip()
            print(f"  Segment {idx}: [{start:.2f}s -> {end:.2f}s] {seg_text}")
    if stt.hotwords:
        print(f"{'Configured Hotwords:':<25} {stt.hotwords}")
    print(f"{'VAD Filter:':<25} {stt.vad_filter} (min_silence: {stt.vad_parameters.get('min_silence_duration_ms', 500)}ms)")
    print("=" * 60)


async def _run_stt_benchmark_cli(
    audio_file: str = "",
    samples_dir: str = "",
    reference_text: str = "",
) -> None:
    """CLI runner for STT benchmark evaluation."""
    from app.voice.stt.benchmark import run_stt_benchmark
    from pathlib import Path

    samples: list[tuple[str, Optional[str]]] = []

    if audio_file and Path(audio_file).exists():
        samples.append((audio_file, reference_text or None))
    elif samples_dir and Path(samples_dir).exists():
        for f in sorted(Path(samples_dir).glob("*.wav")):
            samples.append((str(f), reference_text or None))
    else:
        print("No samples specified. Generating standard target phrase benchmark samples via Kokoro TTS...")
        from app.voice.tts.kokoro_provider import KokoroTTSProvider
        import io
        import soundfile as sf

        tts = KokoroTTSProvider(voice_id="af_heart")
        target_phrases = [
            "Open Firefox and search YouTube.",
            "Launch Helium browser.",
            "Open Kitty and run echo hello world.",
            "Turn on my hotspot.",
            "How is my GPU?",
        ]
        tmp_bench_dir = Path("/tmp/airi_benchmark_samples")
        tmp_bench_dir.mkdir(parents=True, exist_ok=True)
        for i, phrase in enumerate(target_phrases, 1):
            sample_path = str(tmp_bench_dir / f"sample_{i}.wav")
            synth_res = await tts.synthesize(phrase)
            with io.BytesIO(synth_res.audio_data) as buf:
                data, sr = sf.read(buf)
            sf.write(sample_path, data, sr)
            samples.append((sample_path, phrase))

    await run_stt_benchmark(samples)


async def _test_tts() -> None:
    from app.voice.tts.kokoro_provider import KokoroTTSProvider
    try:
        provider = KokoroTTSProvider(voice_id="af_heart")
        if not provider.is_available():
            print("Kokoro TTS is not available.")
            return
            
        print("Synthesizing: 'Hello, this is Airi testing the text to speech engine.'")
        result = await provider.synthesize("Hello, this is Airi testing the text to speech engine.")
        
        import sounddevice as sd
        import soundfile as sf
        import io
        with io.BytesIO(result.audio_data) as f:
            data, fs = sf.read(f)
            sd.play(data, fs)
            sd.wait()
        print("Playback complete.")
    except Exception as e:
        print(f"Error testing TTS: {e}")


async def _run_voice_pipeline(verbose: bool = False) -> None:
    """Run the voice pipeline (PTT loop)."""
    from app.core.logging.logger import setup_logging
    from app.core.events.bus import EventBus
    from app.core.permissions.manager import PermissionManager
    from app.tools.registry import ToolRegistry
    from app.ai.providers.local.provider import LocalProvider
    from app.ai.router import AIRouter
    from app.memory.store import MemoryStore
    from app.agent.orchestrator import AgentOrchestrator
    
    from app.voice.stt.whisper_provider import WhisperSTTProvider
    from app.voice.tts.kokoro_provider import KokoroTTSProvider
    from app.voice.pipeline import AudioPipeline
    from app.core.config.settings import get_settings

    setup_logging(log_level="DEBUG" if verbose else "INFO", pretty_console=True)
    _import_all_tools()

    settings = get_settings()
    event_bus = EventBus()
    registry = ToolRegistry()
    permission_manager = PermissionManager(event_bus, cli_mode=True)

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    memory = MemoryStore(str(data_dir / "memory.db"))
    await memory.initialize()

    # Load Providers
    print("Loading AI Model...")
    local_runtime = None
    if settings.local_ai_enabled and settings.local_ai_runtime == "ollama":
        from app.ai.providers.local.ollama_runtime import OllamaRuntime
        local_runtime = OllamaRuntime(model=settings.local_ai_model, timeout=settings.local_ai_timeout)
    local_provider = LocalProvider(runtime=local_runtime)
    router = AIRouter(local_provider, None)
    
    orchestrator = AgentOrchestrator(
        router=router,
        tool_registry=registry,
        memory=memory,
        event_bus=event_bus,
        permission_manager=permission_manager,
    )
    
    print(f"Loading STT Model ({settings.stt_model} on {settings.stt_device} {settings.stt_compute_type})...")
    stt = WhisperSTTProvider()
    if not stt.is_available():
        print("Error: Faster Whisper not available. Install dependencies.")
        return
        
    print(f"Loading TTS Model ({settings.tts_provider} - {settings.tts_voice})...")
    tts = None
    if settings.tts_provider == "kokoro":
        tts = KokoroTTSProvider(voice_id=settings.tts_voice)
        if not tts.is_available():
            print("Warning: Kokoro TTS not available. Responses will be text only.")

    pipeline = AudioPipeline(stt=stt, tts=tts, event_bus=event_bus)

    print("\n╔══════════════════════════════════════════╗")
    print("║     Airi — Voice Pipeline Test Mode      ║")
    print("║ Press Enter to record. Ctrl+C to exit.   ║")
    print("╚══════════════════════════════════════════╝")

    try:
        while True:
            await pipeline.process_ptt(orchestrator)
    except (KeyboardInterrupt, EOFError):
        print("\n\nGoodbye! ✨")
    finally:
        await memory.close()


if __name__ == "__main__":
    main()
