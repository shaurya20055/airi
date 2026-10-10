from __future__ import annotations
import asyncio
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter

async def get_hotspot_status_dict() -> dict:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "-t", "-f", "UUID,NAME,TYPE,DEVICE", "connection", "show", "--active",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    for line in stdout.decode('utf-8').splitlines():
        if not line:
            continue
        parts = line.split(':')
        if len(parts) >= 4 and parts[2] == '802-11-wireless':
            uuid, name, _, dev = parts[:4]
            # Check if ap mode
            proc2 = await asyncio.create_subprocess_exec(
                "nmcli", "-t", "-f", "802-11-wireless.mode,802-11-wireless.ssid", "connection", "show", uuid,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            out2, _ = await proc2.communicate()
            mode, ssid = "", ""
            for l in out2.decode('utf-8').splitlines():
                if l.startswith("802-11-wireless.mode:"):
                    mode = l.split(':', 1)[1]
                elif l.startswith("802-11-wireless.ssid:"):
                    ssid = l.split(':', 1)[1]
            if mode == "ap":
                return {
                    "active": True,
                    "profile_id": uuid,
                    "profile_name": name,
                    "ssid": ssid,
                    "interface": dev,
                    "connection_uuid": uuid
                }
    return {"active": False}

async def find_existing_profile() -> dict | None:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "-t", "-f", "UUID,NAME,TYPE", "connection", "show",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    for line in out.decode('utf-8').splitlines():
        if ":802-11-wireless" in line and "Airi_Hotspot" in line:
            parts = line.split(':')
            return {"uuid": parts[0], "name": parts[1]}
    return None

async def create_profile(ssid: str, password: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0", 
        "con-name", "Airi_Hotspot", "autoconnect", "false", "ssid", ssid, 
        "--", "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password, 
        "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg", "ipv4.method", "shared",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"Failed to create profile: {err.decode('utf-8')}")
    # Return the new profile UUID by querying it
    profile = await find_existing_profile()
    return profile["uuid"]

async def update_password(uuid: str, password: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "connection", "modify", uuid, "wifi-sec.psk", password,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"Failed to update password: {err.decode('utf-8')}")

async def activate_profile(uuid: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "connection", "up", uuid,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"Failed to activate profile: {err.decode('utf-8')}")

async def deactivate_profile(uuid: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "nmcli", "connection", "down", uuid,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"Failed to deactivate profile: {err.decode('utf-8')}")

@tool(
    name="get_network_status",
    description="Get current network connection status.",
    category="network",
    permission_level=PermissionLevel.SAFE,
)
async def get_network_status() -> ToolResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            "nmcli", "-t", "-f", "NAME,TYPE,STATE", "connection", "show", "--active",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return ToolResult(success=False, error="Failed to query nmcli.")
            
        connections = stdout.decode('utf-8').strip().split('\n')
        active = []
        for c in connections:
            if not c:
                continue
            parts = c.split(':')
            if len(parts) >= 3:
                active.append({"name": parts[0], "type": parts[1], "state": parts[2]})
                
        return ToolResult(success=True, data={"active_connections": active})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="get_hotspot_status",
    description="Authoritatively check if the hotspot is active.",
    category="network",
    permission_level=PermissionLevel.SAFE
)
async def get_hotspot_status() -> ToolResult:
    try:
        status = await get_hotspot_status_dict()
        return ToolResult(success=True, data=status)
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="disable_hotspot",
    description="Disable the active hotspot. NETWORK_CONTROL.",
    category="network",
    permission_level=PermissionLevel.CONFIRM
)
async def disable_hotspot() -> ToolResult:
    try:
        status = await get_hotspot_status_dict()
        if not status.get("active"):
            return ToolResult(success=True, message="Hotspot is already inactive.", data={"already_inactive": True})
            
        uuid = status["profile_id"]
        await deactivate_profile(uuid)
        
        # Verify
        after = await get_hotspot_status_dict()
        if after.get("active"):
            return ToolResult(success=False, error=f"I couldn't confirm that the hotspot turned off. Current state: {after}")
        return ToolResult(success=True, message="Hotspot is off.")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

@tool(
    name="enable_hotspot",
    description="Start the conversational flow to configure and turn on the hotspot.",
    category="network",
    permission_level=PermissionLevel.SAFE
)
async def enable_hotspot() -> ToolResult:
    from app.agent.tasks import HotspotTask
    result = ToolResult(success=True, message="Starting hotspot configuration...")
    result.task = HotspotTask()
    return result

