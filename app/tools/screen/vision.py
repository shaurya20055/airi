"""Model-agnostic vision preprocessing and local vision inference pipeline."""
from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any, Optional

import httpx
from PIL import Image
import structlog

from app.core.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Lock to ensure only one visual inference runs at a time (protects 8GB VRAM)
_VISION_LOCK = asyncio.Lock()

DEFAULT_VISION_PROMPT = (
    "You are inspecting a screenshot of a user's desktop screen. "
    "Analyze the image and return a concise, factual JSON object with these exact keys:\n"
    "{\n"
    '  "application": "<name of active app or website in focus>",\n'
    '  "summary": "<one or two sentences describing what is visible>",\n'
    '  "visible_text": ["<key text snippets, error messages, dialog headers, or button labels>"],\n'
    '  "ui_elements": ["<actionable UI elements like buttons, search bars, tabs, video cards>"],\n'
    '  "uncertainty": "<any ambiguities, partially obscured text, or low confidence notes, or none>"\n'
    "}\n"
    "Output ONLY valid JSON. If text is unreadable or uncertain, explicitly state it in 'uncertainty'."
)


class ScreenVisionProcessor:
    """Preprocesses screenshots and queries the local vision runtime."""

    def __init__(
        self,
        max_dimension: int = 1280,
        jpeg_quality: int = 85,
        ollama_url: str = "http://127.0.0.1:11434",
        timeout: float = 30.0,
    ):
        self.max_dimension = max_dimension
        self.jpeg_quality = jpeg_quality
        self.ollama_url = ollama_url.rstrip("/")
        self.timeout = timeout

    def preprocess_image(self, image_bytes: bytes) -> tuple[str, int, int]:
        """Resize oversized image, encode as JPEG base64, and return (base64, width, height)."""
        with Image.open(io.BytesIO(image_bytes)) as img:
            # Convert to RGB if needed (e.g. RGBA png)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            orig_w, orig_h = img.size
            w, h = orig_w, orig_h

            # Scale down if exceeds max_dimension
            if max(w, h) > self.max_dimension:
                if w >= h:
                    new_w = self.max_dimension
                    new_h = int(h * (self.max_dimension / w))
                else:
                    new_h = self.max_dimension
                    new_w = int(w * (self.max_dimension / h))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = new_w, new_h

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=self.jpeg_quality, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
            return encoded, w, h

    async def analyze_screen(
        self,
        image_bytes: bytes,
        focus_prompt: str = "",
        allow_cloud: bool = False,
    ) -> dict[str, Any]:
        """Perform visual inference on screenshot bytes using local Qwen3-VL."""
        settings = get_settings()

        # Privacy gate: reject if local AI is disabled and allow_cloud is False
        if not settings.local_ai_enabled and not allow_cloud:
            err = "Local AI is disabled and privacy policy prohibits sending screen analysis to cloud."
            logger.warning("screen_vision_cloud_blocked")
            return {
                "success": False,
                "error": "cloud_vision_blocked",
                "message": err,
                "summary": err,
                "uncertainty": "blocked_by_policy",
            }

        t_start = asyncio.get_event_loop().time()
        logger.info("screen_observation_start", prompt=focus_prompt[:60] if focus_prompt else "default")

        try:
            b64_img, proc_w, proc_h = self.preprocess_image(image_bytes)
        except Exception as e:
            logger.error("screen_preprocess_failed", error=str(e))
            return {
                "success": False,
                "error": "invalid_image",
                "message": f"Failed to process image: {e}",
                "summary": "Invalid image data.",
                "uncertainty": "high",
            }

        user_content = DEFAULT_VISION_PROMPT
        if focus_prompt:
            user_content += f"\n\nAdditional user question / focus: {focus_prompt}"

        # Serialize inference to prevent GPU OOM
        async with _VISION_LOCK:
            model_name = settings.local_ai_model or "qwen3-vl:4b-instruct"
            payload = {
                "model": model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": user_content,
                        "images": [b64_img],
                    }
                ],
                "stream": False,
                "options": {
                    "temperature": 0.2,
                },
            }

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as e:
                err_text = e.response.text.lower()
                is_oom = "out of memory" in err_text or "cuda" in err_text or e.response.status_code == 507
                err_code = "gpu_oom" if is_oom else f"http_{e.response.status_code}"
                logger.error("screen_observation_failure", error=err_code, details=e.response.text[:200])
                return {
                    "success": False,
                    "error": err_code,
                    "message": "Local vision model ran out of GPU memory." if is_oom else f"Local vision error: {err_code}",
                    "summary": "Screen observation failed due to model resource limit.",
                    "uncertainty": "high",
                }
            except httpx.RequestError as e:
                logger.error("screen_observation_failure", error="connection_error", details=str(e))
                return {
                    "success": False,
                    "error": "vision_server_unavailable",
                    "message": f"Could not reach local vision runtime: {e}",
                    "summary": "Local vision model is unavailable.",
                    "uncertainty": "high",
                }
            except Exception as e:
                logger.error("screen_observation_failure", error=str(e))
                return {
                    "success": False,
                    "error": "unexpected_vision_error",
                    "message": str(e),
                    "summary": "Unexpected error during screen observation.",
                    "uncertainty": "high",
                }

            msg_content = data.get("message", {}).get("content", "").strip()
            duration = asyncio.get_event_loop().time() - t_start

            # Parse JSON from model output
            parsed = self._extract_json(msg_content)
            summary = parsed.get("summary") or msg_content[:200]
            app_name = parsed.get("application") or ""
            uncertainty = parsed.get("uncertainty") or "none"
            visible_text = parsed.get("visible_text") or []
            ui_elements = parsed.get("ui_elements") or []

            logger.info(
                "screen_observation_success",
                app_name=app_name,
                duration=round(duration, 2),
                uncertainty=uncertainty,
            )

            return {
                "success": True,
                "application": app_name,
                "summary": summary,
                "visible_text": visible_text,
                "ui_elements": ui_elements,
                "uncertainty": uncertainty,
                "raw_response": msg_content,
                "processed_dimensions": (proc_w, proc_h),
            }

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract structured JSON from model response text."""
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            return json.loads(cleaned)
        except Exception:
            # Fallback regex search for JSON block
            import re
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    pass

        return {
            "application": "",
            "summary": text[:200],
            "visible_text": [],
            "ui_elements": [],
            "uncertainty": "unstructured_response",
        }


_vision_processor_instance: Optional[ScreenVisionProcessor] = None


def get_screen_vision_processor() -> ScreenVisionProcessor:
    """Singleton getter for ScreenVisionProcessor."""
    global _vision_processor_instance
    if _vision_processor_instance is None:
        _vision_processor_instance = ScreenVisionProcessor()
    return _vision_processor_instance


def set_screen_vision_processor(processor: ScreenVisionProcessor) -> None:
    """Set global ScreenVisionProcessor instance (useful for testing/mocking)."""
    global _vision_processor_instance
    _vision_processor_instance = processor
