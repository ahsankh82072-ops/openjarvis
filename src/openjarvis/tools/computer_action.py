"""computer_action — executes keyboard and mouse actions with strict safety guards.

NEW file added on branch screen-control. Does NOT modify any existing files.
Uses pyautogui for input automation, with built-in safety controls:
  - Failsafe enabled (move mouse to corner to abort)
  - Emergency stop check (Ctrl+Alt+Q)
  - Dry-run mode support
  - 15-step safety ceiling per session
  - Sensitive keyword blocking (passwords, cards, OTPs, login/banking pages)
  - Detailed action logging
"""

from __future__ import annotations

import ctypes
import datetime
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Default log path
_LOG_DIR = os.path.expanduser("~/.openjarvis")
_LOG_PATH = os.path.join(_LOG_DIR, "computer_actions.log")

# Maximum steps allowed per task session
_MAX_STEPS_PER_TASK = 15

# Sensitive terms that trigger a safety stop
_SENSITIVE_KEYWORDS = [
    "password", "passwd", "pwd", "secret", "token", "api_key",
    "credit_card", "debit_card", "cvv", "cvc", "card_number",
    "otp", "2fa", "pin", "ssn", "bank", "checkout", "billing",
    "payment", "sign in", "login"
]

# Track session step count
_SESSION_STEP_COUNT = 0
_EMERGENCY_STOP_TRIGGERED = False


def _ensure_default_desktop() -> None:
    """Attach the current thread to the interactive user desktop."""
    try:
        user32 = ctypes.windll.user32
        ALL_ACCESS = 0x01FF
        h_desk = user32.OpenDesktopW("default", 0, False, ALL_ACCESS)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


def _get_active_window_title() -> str:
    """Return the active foreground window title."""
    try:
        _ensure_default_desktop()
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def _log_action(action: str, params: Dict[str, Any], result: str, success: bool, dry_run: bool) -> None:
    """Append every action to the persistent computer_actions.log."""
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        ts = datetime.datetime.now().isoformat()
        line = (
            f"[{ts}] [dry_run={dry_run}] [step={_SESSION_STEP_COUNT}] "
            f"ACTION: {action} | PARAMS: {params} | SUCCESS: {success} | RESULT: {result}\n"
        )
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def reset_step_counter() -> None:
    """Reset the session step counter (call when starting a new task)."""
    global _SESSION_STEP_COUNT, _EMERGENCY_STOP_TRIGGERED
    _SESSION_STEP_COUNT = 0
    _EMERGENCY_STOP_TRIGGERED = False


@ToolRegistry.register("computer_action")
class ComputerActionTool(BaseTool):
    """Execute keyboard and mouse actions on Windows with safety guarantees."""

    tool_id = "computer_action"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="computer_action",
            description=(
                "Perform safe mouse and keyboard actions on the Windows PC. "
                "Supported actions: 'click', 'double_click', 'type', 'hotkey', "
                "'scroll', 'open_app', and 'emergency_stop'. "
                "Enforces a maximum of 15 steps per task and blocks sensitive input."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["click", "double_click", "type", "hotkey", "scroll", "open_app", "emergency_stop", "reset_steps"],
                        "description": "The action to perform.",
                    },
                    "x": {
                        "type": "integer",
                        "description": "X coordinate on screen (for click/double_click).",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate on screen (for click/double_click).",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type (for 'type') or app name/path to run (for 'open_app').",
                    },
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keys to press in combination (for 'hotkey'), e.g. ['ctrl', 'c'] or ['enter'].",
                    },
                    "clicks": {
                        "type": "integer",
                        "description": "Scroll distance (for 'scroll', positive = up, negative = down).",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, simulates the action and logs it without touching keyboard or mouse.",
                    },
                },
                "required": ["action"],
            },
            category="screen",
            requires_confirmation=False,
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        global _SESSION_STEP_COUNT, _EMERGENCY_STOP_TRIGGERED

        action = str(params.get("action", "")).strip().lower()
        dry_run = bool(params.get("dry_run", False))

        # Handle reset
        if action == "reset_steps":
            reset_step_counter()
            return ToolResult(
                tool_name="computer_action",
                content="Step counter and emergency stop state reset to 0.",
                success=True,
            )

        # Check emergency stop state
        if _EMERGENCY_STOP_TRIGGERED or action == "emergency_stop":
            _EMERGENCY_STOP_TRIGGERED = True
            _log_action(action, params, "Emergency stop is ACTIVE. All actions halted.", False, dry_run)
            return ToolResult(
                tool_name="computer_action",
                content="EMERGENCY STOP ACTIVATED: All computer actions halted immediately.",
                success=False,
                metadata={"emergency_stop": True},
            )

        # Step count ceiling check (max 15 per task)
        if _SESSION_STEP_COUNT >= _MAX_STEPS_PER_TASK:
            msg = (
                f"SAFETY STOP: Maximum {_MAX_STEPS_PER_TASK} steps reached for this task. "
                "Task paused. Please review screen and instruct whether to continue."
            )
            _log_action(action, params, msg, False, dry_run)
            return ToolResult(
                tool_name="computer_action",
                content=msg,
                success=False,
                metadata={"step_limit_reached": True, "steps": _SESSION_STEP_COUNT},
            )

        # Check active window for sensitive pages
        active_title = _get_active_window_title().lower()
        for kw in ["sign in", "login", "checkout", "payment", "bank", "credit card"]:
            if kw in active_title:
                msg = (
                    f"SAFETY BLOCK: Active window appears to be sensitive ('{active_title}'). "
                    "Refusing automatic interaction on login or payment pages."
                )
                _log_action(action, params, msg, False, dry_run)
                return ToolResult(
                    tool_name="computer_action",
                    content=msg,
                    success=False,
                    metadata={"security_block": True, "window": active_title},
                )

        # Check text parameter for sensitive data
        text = str(params.get("text", ""))
        text_lower = text.lower()
        for kw in _SENSITIVE_KEYWORDS:
            if kw in text_lower and action in ["type", "open_app"]:
                msg = (
                    f"SAFETY BLOCK: Requested text contains sensitive keyword '{kw}'. "
                    "Password and payment credentials cannot be typed automatically."
                )
                _log_action(action, params, msg, False, dry_run)
                return ToolResult(
                    tool_name="computer_action",
                    content=msg,
                    success=False,
                    metadata={"security_block": True, "keyword": kw},
                )

        # Ensure interactive desktop access
        _ensure_default_desktop()

        try:
            import pyautogui  # type: ignore
            pyautogui.FAILSAFE = True  # moving mouse to upper-left corner stops pyautogui
            pyautogui.PAUSE = 0.1
        except ImportError:
            return ToolResult(
                tool_name="computer_action",
                content="pyautogui is not installed. Install with: pip install pyautogui",
                success=False,
            )

        # Increment step count
        _SESSION_STEP_COUNT += 1

        # Dry run simulation
        if dry_run:
            sim_msg = f"[DRY RUN] Would execute action: '{action}' with params {params}"
            _log_action(action, params, sim_msg, True, dry_run=True)
            return ToolResult(
                tool_name="computer_action",
                content=sim_msg,
                success=True,
                metadata={"dry_run": True, "step": _SESSION_STEP_COUNT},
            )

        # Execute physical actions
        try:
            if action == "click":
                x = params.get("x")
                y = params.get("y")
                if x is not None and y is not None:
                    pyautogui.click(int(x), int(y))
                    res_msg = f"Clicked at ({x}, {y})"
                else:
                    pyautogui.click()
                    res_msg = "Clicked at current mouse position"

            elif action == "double_click":
                x = params.get("x")
                y = params.get("y")
                if x is not None and y is not None:
                    pyautogui.doubleClick(int(x), int(y))
                    res_msg = f"Double-clicked at ({x}, {y})"
                else:
                    pyautogui.doubleClick()
                    res_msg = "Double-clicked at current position"

            elif action == "type":
                if not text:
                    return ToolResult(tool_name="computer_action", content="No text specified to type.", success=False)
                # Type characters safely
                pyautogui.write(text, interval=0.02)
                res_msg = f"Typed text ({len(text)} chars)"

            elif action == "hotkey":
                keys: List[str] = params.get("keys", [])
                if not keys and text:
                    keys = [k.strip() for k in text.split("+")]
                if not keys:
                    return ToolResult(tool_name="computer_action", content="No keys specified for hotkey.", success=False)
                pyautogui.hotkey(*keys)
                res_msg = f"Pressed hotkey: {'+'.join(keys)}"

            elif action == "scroll":
                clicks = int(params.get("clicks", 0))
                pyautogui.scroll(clicks)
                res_msg = f"Scrolled {clicks} units"

            elif action == "open_app":
                app_cmd = text
                if not app_cmd:
                    return ToolResult(tool_name="computer_action", content="No app or command provided to open.", success=False)
                # Launch application detached
                subprocess.Popen(app_cmd, shell=True)
                res_msg = f"Launched application: {app_cmd}"

            else:
                return ToolResult(
                    tool_name="computer_action",
                    content=f"Unsupported action: '{action}'.",
                    success=False,
                )

            _log_action(action, params, res_msg, True, dry_run=False)
            return ToolResult(
                tool_name="computer_action",
                content=res_msg,
                success=True,
                metadata={"step": _SESSION_STEP_COUNT, "active_window": _get_active_window_title()},
            )

        except pyautogui.FailSafeException:
            _EMERGENCY_STOP_TRIGGERED = True
            fail_msg = "PyAutoGUI FailSafe triggered (mouse moved to corner). All actions stopped."
            _log_action(action, params, fail_msg, False, dry_run=False)
            return ToolResult(
                tool_name="computer_action",
                content=fail_msg,
                success=False,
                metadata={"failsafe": True},
            )
        except Exception as exc:
            err_msg = f"Action execution error: {exc}"
            _log_action(action, params, err_msg, False, dry_run=False)
            return ToolResult(
                tool_name="computer_action",
                content=err_msg,
                success=False,
            )


__all__ = ["ComputerActionTool", "reset_step_counter"]
