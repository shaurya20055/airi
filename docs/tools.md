# Tool System

Airi interacts with the operating system through a highly structured Tool System. Each tool is an isolated function mapped to a specific capability.

## Available Tools

### OS & Audio
- `set_volume(level: int)`: Sets system volume (0-100).
- `get_volume() -> int`: Returns current volume.
- `mute()`: Mutes system audio.
- `unmute()`: Unmutes system audio.
- `toggle_mute()`: Toggles audio mute state.
- `set_brightness(level: int)`: Sets screen brightness.
- `get_brightness() -> int`: Returns current brightness.
- `launch_application(name: str)`: Launches a GUI application.
- `list_running_applications() -> list[str]`: Lists active GUI windows.
- `close_application(name: str)`: Closes an application gracefully.

### System Control
- `lock_screen()`: Locks the current Wayland session.
- `shutdown()`: Powers off the machine (Requires CONFIRM).
- `reboot()`: Reboots the machine (Requires CONFIRM).
- `suspend()`: Suspends the machine.
- `get_system_info() -> dict`: Returns OS, kernel, and hardware info.
- `get_cpu_usage() -> float`: Returns CPU usage percentage.
- `get_memory_usage() -> dict`: Returns memory stats.
- `get_disk_usage() -> dict`: Returns disk space stats.
- `get_uptime() -> str`: Returns system uptime.

### Screen
- `take_screenshot(path: str)`: Saves a screenshot to disk.
- `capture_screen_base64() -> str`: Returns the current screen as a base64 encoded image.

### Files
- `read_file(path: str) -> str`: Reads contents of a text file.
- `list_directory(path: str) -> list[str]`: Lists files in a directory.
- `search_files(query: str, path: str)`: Searches for files by name.
- `open_file(path: str)`: Opens a file in the default application.

## Permission Levels

Every tool must declare a permission level:
- **SAFE**: Can run automatically (e.g., `get_volume`, `get_system_info`).
- **CONFIRM**: Requires explicit user confirmation via UI before execution (e.g., `shutdown`, `rm`).
- **DANGEROUS**: High-risk actions that require elevated privileges or strong authentication.
- **BLOCKED**: Disabled entirely.

## Creating a New Tool

To create a new tool, define an async function and use the `@tool` decorator. Pydantic is used internally to validate the arguments.

```python
from app.tools.registry import tool

@tool(name="greet", description="Greets the user by name", permission="SAFE")
async def greet_tool(name: str) -> str:
    """Greets the user. Useful for testing."""
    return f"Hello, {name}!"
```

## Tool Result Schema

All tools return data that is standardized before being passed back to the AI provider. Errors are caught and returned as structured error messages, preventing the agent from crashing.

## OpenAI Function Calling Format

The Tool Registry automatically converts Python type hints and docstrings into the JSON Schema format required by OpenAI's Function Calling API, allowing seamless integration with cloud providers.
