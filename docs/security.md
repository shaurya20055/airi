# Security Model

As an AI assistant with deep integration into the host operating system, security and safety are top priorities. Airi implements a robust, multi-tiered security model.

## Permission Levels

Every action (Tool) within Airi is tagged with a permission level. The Agent Loop checks these permissions before execution.

1. **SAFE**: The tool can run automatically without user intervention. These are read-only operations or non-destructive state changes (e.g., `get_volume`, `take_screenshot`).
2. **CONFIRM**: The tool requires explicit user confirmation via the CLI or UI before execution. Used for destructive or disruptive actions (e.g., `shutdown`, `rm`, `kill`).
3. **DANGEROUS**: High-risk actions that require elevated privileges. By default, Airi will refuse to execute these unless specifically authenticated.
4. **BLOCKED**: Tools that are completely disabled for the current session.

## Session Permissions

When starting Airi, you can restrict the maximum permission level for the session:
```bash
python -m app --max-permission=SAFE
```
In this mode, any request that requires `CONFIRM` or higher will be automatically denied.

## Untrusted Data Handling

When the AI agent reads data from the web or external files, that data is considered **untrusted**. Tools that execute shell commands or write files strictly sanitize their inputs to prevent Prompt Injection attacks from escalating into Remote Code Execution.

- Never use `os.system` with raw AI output.
- Always use structured tool arguments and `subprocess.run` with array-based arguments.

## API Key Management

API keys (e.g., `OPENAI_API_KEY`) are read strictly from the `.env` file or environment variables. They are **never** logged to stdout, debug files, or stored in short-term memory transcripts. The logger filters out sensitive configuration strings automatically.

## Audio Privacy

Airi is Local-First. By default, your microphone audio is processed entirely on your local machine using `faster-whisper`. No audio data is ever sent to the cloud.

## Shell Command Restrictions

Arbitrary shell command execution is disabled by default. The agent must use specific, constrained tools (like `launch_application` or `close_application`) rather than spawning arbitrary `bash` shells.

## Web Content Safety

Browser automation tools operate in a sandboxed environment with strict CORS and execution policies to prevent malicious scripts from interacting with the Airi agent directly.
