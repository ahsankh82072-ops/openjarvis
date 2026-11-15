"""describe_screen — sends a screenshot to a vision model and returns a description.

NEW file added on branch screen-control. Does NOT modify any existing files.
Calls Ollama locally (moondream by default) — no cloud, no internet needed.
"""

from __future__ import annotations

import base64
import ctypes
import json
import urllib.error
import urllib.request
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Default Ollama endpoint (already running on the user's machine)
_OLLAMA_HOST = "http://localhost:11434"
# Default vision model — small (828 MB), runs fine on 8 GB RAM
_DEFAULT_VISION_MODEL = "moondream"


def _ensure_default_desktop() -> None:
    """Ensure the current thread is attached to the user's interactive 'default' desktop."""
    try:
        user32 = ctypes.windll.user32
        ALL_ACCESS = 0x01FF
        h_desk = user32.OpenDesktopW("default", 0, False, ALL_ACCESS)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


def _ask_vision_model(
    b64_image: str,
    prompt: str,
    model: str = _DEFAULT_VISION_MODEL,
    ollama_host: str = _OLLAMA_HOST,
) -> str:
    """Send a base64 PNG image + text prompt to Ollama and return the reply."""
    url = f"{ollama_host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64_image],  # Ollama multimodal API accepts base64 strings
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", "").strip()
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {ollama_host}. "
            f"Make sure Ollama is running. Error: {exc}"
        ) from exc


@ToolRegistry.register("describe_screen")
class DescribeScreenTool(BaseTool):
    """Ask a vision AI model to describe what is currently on the screen.

    Takes a screenshot automatically (via screen_capture logic), sends it to
    the moondream vision model running in Ollama, and returns a plain-English
    description. Use this to answer questions like:
      - "What is on my screen?"
      - "Summarise this page."
      - "What app is open?"
      - "Is there an error message?"
    """

    tool_id = "describe_screen"
    is_local = True  # Ollama runs locally; no cloud calls

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="describe_screen",
            description=(
                "Take a screenshot and ask a local vision AI to describe it. "
                "Returns a plain-English description of what is currently visible "
                "on the user's screen. Good for 'what is on my screen?', "
                "'summarise this page', or checking whether a task succeeded."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "What to ask about the screen. "
                            "Default: 'Describe everything you see on this screen in detail.'"
                        ),
                    },
                    "model": {
                        "type": "string",
                        "description": (
                            "Vision model to use (must be installed in Ollama). "
                            "Default: 'moondream'. Alternative: 'llava:7b'."
                        ),
                    },
                    "monitor": {
                        "type": "integer",
                        "description": "Which monitor to capture (1 = primary). Default 1.",
                    },
                },
                "required": [],
            },
            category="screen",
            timeout_seconds=90.0,  # vision inference can be slow on CPU
        )

    def execute(self, **params: Any) -> ToolResult:
        question: str = params.get(
            "question",
            "Describe everything you see on this screen in detail. "
            "List every visible app, window, text, button, and any important content.",
        )
        model: str = params.get("model", _DEFAULT_VISION_MODEL)
        monitor_idx: int = int(params.get("monitor", 1))

        # --- Step 1: Take a screenshot ---
        try:
            import mss  # type: ignore
            import mss.tools  # type: ignore
        except ImportError:
            return ToolResult(
                tool_name="describe_screen",
                content="mss is not installed. Run: pip install mss",
                success=False,
            )

        _ensure_default_desktop()
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor_idx >= len(monitors):
                    monitor_idx = 1
                region = monitors[monitor_idx]
                sct_img = sct.grab(region)
                png_bytes: bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
        except Exception as exc:
            return ToolResult(
                tool_name="describe_screen",
                content=f"Screenshot failed: {exc}",
                success=False,
            )

        # --- Step 2: Resize to keep inference fast ---
        try:
            import io
            from PIL import Image  # type: ignore
            img = Image.open(io.BytesIO(png_bytes))
            img.thumbnail((1280, 720), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="PNG")
            png_bytes = out.getvalue()
        except ImportError:
            pass  # Pillow not installed — use original size

        b64_image = base64.b64encode(png_bytes).decode("utf-8")

        # --- Step 3: Get active window title ---
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            window_title = buf.value or "Unknown"
        except Exception:
            window_title = "Unknown"

        # --- Step 4: Ask the vision model ---
        try:
            description = _ask_vision_model(b64_image, question, model=model)
        except RuntimeError as exc:
            return ToolResult(
                tool_name="describe_screen",
                content=str(exc),
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="describe_screen",
                content=f"Vision model error: {exc}",
                success=False,
            )

        if not description:
            return ToolResult(
                tool_name="describe_screen",
                content="Vision model returned an empty response. Try again.",
                success=False,
            )

        # --- Return combined result ---
        full_result = (
            f"Active window: {window_title}\n\n"
            f"Screen description:\n{description}"
        )

        return ToolResult(
            tool_name="describe_screen",
            content=full_result,
            success=True,
            metadata={
                "active_window": window_title,
                "model": model,
                "question": question,
                "image_bytes": len(png_bytes),
            },
        )


__all__ = ["DescribeScreenTool"]
