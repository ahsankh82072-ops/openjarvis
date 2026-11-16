"""screen_capture — takes a screenshot of the current screen and returns it.

NEW file added on branch screen-control. Does NOT modify any existing files.
Uses `mss` for screenshot capture and `ctypes` (Windows built-in) for the
active window title. No network calls; fully local.
"""

from __future__ import annotations

import base64
import ctypes
import io
import time
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Maximum pixel dimensions after resize (keeps images small for the model)
_MAX_WIDTH = 1280
_MAX_HEIGHT = 720


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


def _get_active_window_title() -> str:
    """Return the title of the currently focused window (Windows only)."""
    try:
        _ensure_default_desktop()
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return "Unknown"
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or "Unknown"
    except Exception:
        return "Unknown"


def _resize_image(img_bytes: bytes, max_w: int = _MAX_WIDTH, max_h: int = _MAX_HEIGHT) -> bytes:
    """Resize PNG bytes to fit within max_w × max_h, keeping aspect ratio."""
    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(img_bytes))
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except ImportError:
        # Pillow not installed — return original image unchanged
        return img_bytes


@ToolRegistry.register("screen_capture")
class ScreenCaptureTool(BaseTool):
    """Take a screenshot of the current screen and return it as base64 PNG.

    Also returns the active window title so the agent knows which app
    is in focus. The image is resized to at most 1280×720 to keep it
    small enough for fast vision-model inference.
    """

    tool_id = "screen_capture"
    is_local = True  # no network; fully offline

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_capture",
            description=(
                "Take a screenshot of the user's screen. "
                "Returns the screenshot as a base64-encoded PNG string and the "
                "title of the active (focused) window. "
                "Use this before any computer-control action so you can see the "
                "current state of the screen."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": (
                            "Which monitor to capture. 0 = all monitors combined, "
                            "1 = primary monitor (default), 2 = second monitor, etc."
                        ),
                    },
                    "resize": {
                        "type": "boolean",
                        "description": (
                            "Whether to resize the image to fit 1280×720 before "
                            "returning it. Default true (saves memory and is faster "
                            "for the vision model)."
                        ),
                    },
                },
                "required": [],
            },
            category="screen",
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        monitor_idx: int = int(params.get("monitor", 1))
        do_resize: bool = bool(params.get("resize", True))

        # --- Import mss ---
        try:
            import mss  # type: ignore
            import mss.tools  # type: ignore
        except ImportError:
            return ToolResult(
                tool_name="screen_capture",
                content=(
                    "mss is not installed. Install it with:\n"
                    "  pip install mss"
                ),
                success=False,
            )

        t0 = time.time()
        _ensure_default_desktop()
        try:
            with mss.mss() as sct:
                monitors = sct.monitors  # index 0 = all, 1+ = individual
                if monitor_idx >= len(monitors):
                    monitor_idx = 1  # fall back to primary
                region = monitors[monitor_idx]
                sct_img = sct.grab(region)
                # mss returns BGRA — convert to PNG bytes
                png_bytes: bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
        except Exception as exc:
            return ToolResult(
                tool_name="screen_capture",
                content=f"Screenshot failed: {exc}",
                success=False,
            )

        # --- Optional resize ---
        if do_resize:
            png_bytes = _resize_image(png_bytes)

        # --- Active window title ---
        window_title = _get_active_window_title()

        # --- Encode as base64 so the model can receive it as text ---
        b64_image = base64.b64encode(png_bytes).decode("utf-8")

        elapsed = round(time.time() - t0, 2)

        return ToolResult(
            tool_name="screen_capture",
            content=b64_image,
            success=True,
            metadata={
                "active_window": window_title,
                "monitor": monitor_idx,
                "size_bytes": len(png_bytes),
                "capture_seconds": elapsed,
                "format": "png/base64",
            },
        )


__all__ = ["ScreenCaptureTool"]
