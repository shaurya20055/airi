from __future__ import annotations
import shlex
import re
from typing import Any
from app.core.permissions.levels import PermissionLevel

class CommandPolicy:
    LOW_RISK_COMMANDS = {
        "echo", "pwd", "ls", "whoami", "date", "uptime", "uname",
        "id", "which", "whereis", "printf", "cat", "head", "tail",
        "grep", "find", "df", "du", "free", "nvidia-smi"
    }

    METACHARACTERS = {"|", "&&", "||", ";", ">", ">>", "<", "$(", "`", "*"}

    @classmethod
    def classify(cls, args: dict[str, Any]) -> tuple[PermissionLevel, str]:
        command = args.get("command", "")
        if not command:
            return PermissionLevel.SAFE, ""

        # Check for shell metacharacters
        for meta in cls.METACHARACTERS:
            if meta in command:
                return PermissionLevel.DANGEROUS, f"Contains shell metacharacter '{meta}'"

        try:
            parts = shlex.split(command)
        except ValueError as e:
            return PermissionLevel.DANGEROUS, f"Malformed command string: {e}"

        if not parts:
            return PermissionLevel.SAFE, ""

        base_cmd = parts[0]
        if base_cmd in cls.LOW_RISK_COMMANDS:
            return PermissionLevel.SAFE, ""
        
        # High-risk explicitly listed in prompt: sudo, rm, mv, cp, chmod, chown, dd, mkfs, mount, umount, systemctl, reboot, shutdown, poweroff, kill, pkill, useradd, passwd, iptables
        DANGEROUS_CMDS = {
            "sudo", "rm", "mv", "cp", "chmod", "chown", "dd", "mkfs", "mount", 
            "umount", "systemctl", "reboot", "shutdown", "poweroff", "kill", 
            "pkill", "useradd", "passwd", "iptables"
        }
        if base_cmd in DANGEROUS_CMDS:
            return PermissionLevel.DANGEROUS, f"Command '{base_cmd}' modifies system or data"

        # Default to CONFIRM for anything else not explicitly low-risk
        return PermissionLevel.CONFIRM, f"Command '{base_cmd}' is not in the explicit safe list"
