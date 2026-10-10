from __future__ import annotations
import re
import time
from abc import ABC, abstractmethod
import structlog
from app.tools.os_tools.desktop_parser import DesktopEntry

logger = structlog.get_logger(__name__)

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


class ApplicationClarificationTask(InteractiveTask):
    """Interactive task for clarifying and confirming application resolution."""

    def __init__(
        self,
        original_user_request: str,
        raw_transcribed_name: str,
        candidates: list[DesktopEntry],
        confidence_scores: list[float] | None = None,
        timeout_seconds: float = 60.0,
    ):
        self.original_user_request = original_user_request
        self.raw_transcribed_name = raw_transcribed_name
        self.normalized_search_text = raw_transcribed_name.lower().strip()
        self.candidates = candidates
        self.candidate_ids = [c.app_id or c.path for c in candidates]
        self.canonical_names = [c.name for c in candidates]
        self.confidence_scores = confidence_scores or [1.0] * len(candidates)
        self.selected_candidate = candidates[0] if len(candidates) == 1 else None
        self.clarification_stage = "CONFIRM_SINGLE" if len(candidates) == 1 else "CHOOSE_MULTIPLE"
        self.timeout_seconds = timeout_seconds
        self.created_at = time.time()
        self.is_complete = False
        self.permission_manager = None
        self.correction_instruction: str | None = None

    async def start(self) -> str:
        if self.clarification_stage == "CONFIRM_SINGLE":
            logger.info(
                "application_clarification_requested",
                query=self.raw_transcribed_name,
                candidate=self.canonical_names[0],
            )
            return f"I couldn't find {self.raw_transcribed_name}, but I found {self.canonical_names[0]}. Did you mean that?"
        else:
            logger.info(
                "application_clarification_requested",
                query=self.raw_transcribed_name,
                candidates=self.canonical_names,
            )
            return f"Multiple applications match '{self.raw_transcribed_name}': {', '.join(self.canonical_names)}. Which one did you mean?"

    async def handle_input(self, text: str) -> str:
        if time.time() - self.created_at > self.timeout_seconds:
            self.is_complete = True
            self.clarification_stage = "CANCELLED"
            return "Application confirmation timed out."

        clean = text.lower().strip()

        # 1. Explicit cancellation / negative
        is_negative = (
            clean in {"no", "nope", "cancel", "neither", "none of those", "none", "don't", "dont", "nevermind", "stop", "no the browser", "no, the browser"}
            or bool(re.match(r"^(?:no|nope|cancel|neither|none|none\s+of\s+those|don't|dont|nevermind|stop)(?:[,\s]+(?:the\s+)?browser)?\b", clean))
        )
        if is_negative:
            logger.info("application_clarification_rejected", query=self.raw_transcribed_name)
            self.is_complete = True
            self.clarification_stage = "CANCELLED"
            self.correction_instruction = None
            if self.selected_candidate:
                return f"Okay, I won't launch {self.selected_candidate.name}."
            return "Okay, cancelled."

        # 2. Correction / replacement instruction (browser, video, search, or redirect)
        from app.agent.task_context import is_browser_result_reference
        is_correction = (
            is_browser_result_reference(text)
            or bool(re.search(r"\b(firefox|chrome|helium|browser|youtube|video|electroboom|search\s+result|on\s+the\s+page|that\s+we\s+just\s+opened)\b", clean))
            or bool(re.match(r"^(?:i\s+meant|i\s+was\s+talking\s+about|not\s+that|actually|instead|i\s+said)\b", clean))
        )
        if is_correction:
            logger.info(
                "application_clarification_abandoned_for_correction",
                query=self.raw_transcribed_name,
                correction=text,
            )
            self.is_complete = True
            self.clarification_stage = "ABANDONED"
            self.correction_instruction = text
            return f"Abandoning application clarification for '{text}'."

        # 3. Handle CONFIRM_SINGLE stage
        if self.clarification_stage == "CONFIRM_SINGLE":
            affirmative_pattern = r"\b(?:yes|yeah|yep|sure|correct|that's right|thats right|that one|open it|launch it|please do|ok|okay|do it)\b"
            is_affirmative = bool(
                re.search(affirmative_pattern, clean)
                or (self.selected_candidate and clean in {
                    self.selected_candidate.name.lower(),
                    f"open {self.selected_candidate.name.lower()}",
                    f"launch {self.selected_candidate.name.lower()}",
                })
            )
            if is_affirmative and self.selected_candidate:
                logger.info("application_clarification_confirmed", confirmed_app=self.selected_candidate.name)
                self.is_complete = True
                self.clarification_stage = "DONE"
                return await self._launch_candidate(self.selected_candidate)

            # Check if user named a completely different app command (e.g. "open gimp", "launch calculator")
            app_match = re.search(r"^(?:open|launch|start|run)\s+([a-zA-Z0-9_\-\.\s]{1,40})$", clean)
            if app_match:
                new_app = app_match.group(1).strip()
                self.is_complete = True
                self.clarification_stage = "ABANDONED"
                self.correction_instruction = text
                return f"Switching to {new_app}."

            return f"Please answer 'yes' to launch {self.selected_candidate.name}, or 'no' to cancel."

        # 4. Handle CHOOSE_MULTIPLE stage
        elif self.clarification_stage == "CHOOSE_MULTIPLE":
            chosen = None
            # Strict ordinal / numeric selection
            ordinal_1 = {"1", "number 1", "option 1", "#1", "first", "first one", "the first one", "the first"}
            ordinal_2 = {"2", "number 2", "option 2", "#2", "second", "second one", "the second one", "the second"}
            ordinal_3 = {"3", "number 3", "option 3", "#3", "third", "third one", "the third one", "the third"}

            if clean in ordinal_1 and len(self.candidates) >= 1:
                chosen = self.candidates[0]
            elif clean in ordinal_2 and len(self.candidates) >= 2:
                chosen = self.candidates[1]
            elif clean in ordinal_3 and len(self.candidates) >= 3:
                chosen = self.candidates[2]
            else:
                for cand in self.candidates:
                    c_name = cand.name.lower()
                    if clean in {c_name, f"open {c_name}", f"launch {c_name}", f"choose {c_name}", f"select {c_name}"}:
                        chosen = cand
                        break

            if chosen:
                self.selected_candidate = chosen
                self.is_complete = True
                self.clarification_stage = "DONE"
                logger.info("application_clarification_confirmed", confirmed_app=chosen.name)
                return await self._launch_candidate(chosen)

            # Check if user named a new app command
            app_match = re.search(r"^(?:open|launch|start|run)\s+([a-zA-Z0-9_\-\.\s]{1,40})$", clean)
            if app_match:
                new_app = app_match.group(1).strip()
                self.is_complete = True
                self.clarification_stage = "ABANDONED"
                self.correction_instruction = text
                return f"Switching to {new_app}."

            return f"Please select one of: {', '.join(self.canonical_names)}, or say 'cancel'."

        return "Application clarification is in an unknown state."

    async def _launch_candidate(self, candidate: DesktopEntry) -> str:
        from app.core.permissions.levels import PermissionLevel
        if self.permission_manager:
            allowed = await self.permission_manager.request_permission(
                tool_name="launch_application",
                args={"name": candidate.name},
                level=PermissionLevel.SAFE,
                description=f"Launch {candidate.name}",
            )
            if not allowed:
                return f"Permission denied to launch {candidate.name}."

        from app.tools.os_tools.apps import launch_desktop_entry
        success, message = await launch_desktop_entry(candidate)
        return message


