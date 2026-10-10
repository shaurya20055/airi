from __future__ import annotations
import re
from abc import ABC, abstractmethod

class InteractiveTask(ABC):
    permission_manager = None
    is_complete: bool = False

    @abstractmethod
    async def start(self) -> str:
        """Start the task and return the first prompt."""
        pass

    @abstractmethod
    async def handle_input(self, text: str) -> str:
        """Process user input and return the next prompt or final result."""
        pass

class HotspotTask(InteractiveTask):
    def __init__(self):
        self.state = "START"
        self.existing_profile = None
        self.ssid = ""
        self.password = ""
        
    async def start(self) -> str:
        from app.tools.system.network import get_hotspot_status_dict, find_existing_profile
        
        status = await get_hotspot_status_dict()
        if status.get("active"):
            self.is_complete = True
            return "The hotspot is already active."
            
        self.existing_profile = await find_existing_profile()
        if self.existing_profile:
            self.state = "CHOOSING_REUSE_OR_NEW"
            return "Do you want to reuse your previous hotspot settings or create a new hotspot?"
        else:
            self.state = "WAITING_FOR_SSID"
            return "What SSID should I use?"

    async def handle_input(self, text: str) -> str:
        if self.state == "CHOOSING_REUSE_OR_NEW":
            if re.search(r'\b(reuse|old|same|previous|keep)\b', text, re.I):
                self.state = "CHOOSING_PASSWORD_POLICY"
                return "Keep the existing password or set a new one?"
            elif re.search(r'\b(new|create|change)\b', text, re.I):
                self.state = "WAITING_FOR_SSID"
                return "What SSID should I use?"
            else:
                return "Please answer 'reuse' to use previous settings, or 'new' to create a new hotspot."
                
        elif self.state == "CHOOSING_PASSWORD_POLICY":
            if re.search(r'\b(keep|same|old)\b', text, re.I):
                self.state = "READY_TO_ACTIVATE"
                return await self._activate()
            elif re.search(r'\b(change|new)\b', text, re.I):
                self.state = "WAITING_FOR_PASSWORD"
                return "What password should I use?"
            else:
                return "Please answer 'keep' to keep the existing password, or 'change' to set a new one."
                
        elif self.state == "WAITING_FOR_SSID":
            ssid = text.strip()
            if not ssid or len(ssid) > 32:
                return "Invalid SSID. It cannot be empty or longer than 32 characters. What SSID should I use?"
            self.ssid = ssid
            self.state = "WAITING_FOR_PASSWORD"
            return "What password should I use?"
            
        elif self.state == "WAITING_FOR_PASSWORD":
            password = text.strip()
            if len(password) < 8 or len(password) > 63:
                return "Invalid password. It must be between 8 and 63 characters long. What password should I use?"
            self.password = password
            self.state = "READY_TO_ACTIVATE"
            return await self._activate()
            
        return "Hotspot configuration is in an unknown state."
        
    async def _activate(self) -> str:
        from app.core.permissions.levels import PermissionLevel
        from app.tools.system.network import create_profile, update_password, activate_profile
        
        args = {}
        if self.ssid:
            args["ssid"] = self.ssid
            args["password"] = "***"  # Redact before passing to PM
        elif self.password:
            args["password"] = "***"
        else:
            args["reuse_existing"] = True
            
        allowed = await self.permission_manager.request_permission(
            tool_name="enable_hotspot",
            args=args,
            level=PermissionLevel.CONFIRM,
            description="Activate WiFi Hotspot"
        )
        
        if not allowed:
            self.is_complete = True
            return "Hotspot activation cancelled."
            
        self.state = "ACTIVATING"
        
        try:
            if self.ssid and self.password:
                uuid = await create_profile(self.ssid, self.password)
            elif self.password and self.existing_profile:
                uuid = self.existing_profile["uuid"]
                await update_password(uuid, self.password)
            elif self.existing_profile:
                uuid = self.existing_profile["uuid"]
            else:
                self.is_complete = True
                return "Failed to determine profile configuration."
                
            await activate_profile(uuid)
            
            from app.tools.system.network import get_hotspot_status_dict
            status = await get_hotspot_status_dict()
            self.is_complete = True
            
            if status.get("active"):
                return "Hotspot is on."
            else:
                return "I couldn't confirm that the hotspot turned on."
        except Exception as e:
            self.is_complete = True
            return f"Failed to activate hotspot: {str(e)}"

