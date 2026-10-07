# Setup Guide

This guide covers how to set up Airi on an Arch Linux system running Hyprland.

## System Requirements

- OS: Arch Linux
- Display Server: Wayland (Hyprland recommended)
- Python: 3.12 or newer
- Hardware: Modern CPU, optional GPU for local AI (NVIDIA RTX series recommended)

## 1. System Dependencies

Airi relies on standard Linux utilities to interact with your system. Install them using pacman:

```bash
sudo pacman -S \
    pipewire-pulse \
    brightnessctl \
    grim \
    slurp \
    firefox
```

## 2. Python Environment Setup

We recommend using a virtual environment to isolate Python dependencies:

```bash
cd /home/pwner/Documents/airi
python -m venv venv
source venv/bin/activate
```

## 3. Install Python Dependencies

Install the core application requirements:

```bash
pip install -r requirements.txt
```

*(Optional)* Install extras for Voice or Cloud integrations if using setup tools:
```bash
pip install -r requirements-voice.txt
```

## 4. Configuration

Copy the example configuration file and adjust it to your needs:

```bash
cp .env.example .env
```

Edit `.env` using your preferred text editor. At a minimum, set your preferred provider.

## 5. Verifying Installation

Airi includes a built-in diagnostic tool to verify that all system dependencies are installed and accessible:

```bash
python -m app --diagnostics
```
This will check for binaries like `pactl` and `brightnessctl`, and ensure your user has the correct permissions.

## 6. Optional: Cloud AI Setup

If you wish to use OpenAI for advanced reasoning, add your API key to `.env`:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key-here
```

## 7. Optional: Voice Setup

For voice interaction, Airi uses `faster-whisper` (STT) and `kokoro` (TTS). Make sure you have installed the voice requirements, then enable the voice pipeline in your `.env`. Model weights will be downloaded automatically on first run.
