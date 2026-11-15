"""
worker.py — Background execution engine for Jarvis Desktop App.
Handles Ollama API calls with keep_alive & timeout retries, vision inference,
screen capture, action execution, emergency stop hotkeys, and voice input.
"""

from __future__ import annotations

import base64
import ctypes
import datetime
import io
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import openjarvis.tools
from config import config
from openjarvis.tools.computer_action import ComputerActionTool, reset_step_counter
from openjarvis.tools.describe_screen import DescribeScreenTool
from openjarvis.tools.screen_capture import ScreenCaptureTool

# Critical keywords that require user confirmation
_CRITICAL_ACTIONS = [
    "send message", "send email", "email", "delete file", "delete folder",
    "remove", "rm", "purchase", "buy", "pay", "payment", "order",
    "close unsaved", "shutdown", "reboot", "restart", "format", "settings"
]

_LOG_FILE = os.path.join(_REPO_ROOT, "computer_actions.log")


class JarvisWorker:
    """Manages asynchronous tasks without blocking the GUI."""

    def __init__(self, callbacks: Dict[str, Callable[..., Any]]) -> None:
        """
        callbacks dictionary expects:
            - on_status(state: str)
            - on_chat(sender: str, text: str)
            - on_plan(plan_text: str, is_risky: bool)
            - on_screenshot(img_bytes: bytes, window_title: str)
            - on_log(timestamp: str, step: int, action: str, result: str, success: bool)
            - on_task_done()
        """
        self.cb = callbacks
        self.emergency_stop = False
        self.active_task_thread: Optional[threading.Thread] = None

        # Approval signals from GUI
        self.plan_approval_event = threading.Event()
        self.plan_approved = False

        self.step_approval_event = threading.Event()
        self.step_approved = False

        # Tools
        self.screen_tool = ScreenCaptureTool()
        self.describe_tool = DescribeScreenTool()
        self.action_tool = ComputerActionTool()

        # Start background Ctrl+Alt+Q emergency listener
        self._exit_listener = False
        self.hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        self.hotkey_thread.start()

    def _hotkey_listener(self) -> None:
        """Global emergency stop listener for Ctrl+Alt+Q."""
        user32 = ctypes.windll.user32
        while not self._exit_listener:
            try:
                ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
                alt = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0
                q_key = (user32.GetAsyncKeyState(0x51) & 0x8000) != 0
                if ctrl and alt and q_key:
                    self.stop()
                    time.sleep(1.0)
            except Exception:
                pass
            time.sleep(0.05)

    def stop(self) -> None:
        """Triggers emergency stop immediately."""
        self.emergency_stop = True
        self.action_tool.execute(action="emergency_stop")
        self.plan_approval_event.set()
        self.step_approval_event.set()
        self.cb.get("on_status", lambda s: None)("Stopped")
        self.cb.get("on_chat", lambda s, t: None)(
            "Jarvis", "🚨 EMERGENCY STOP ACTIVATED: All computer actions halted immediately."
        )
        self._speak("Emergency stop activated. All actions halted.")

    def _log_action(self, step: int, action: str, result: str, success: bool) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{ts}] [step={step}] ACTION: {action} | RESULT: {result} | SUCCESS: {success}\n"
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception:
            pass
        self.cb.get("on_log", lambda *args: None)(ts, step, action, result, success)

    def _speak(self, text: str) -> None:
        """Speak response if voice is enabled in config."""
        if not config.voice_enabled:
            return

        def _tts():
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 185)
                clean = re.sub(r"[*_#`•<>]", "", text)
                engine.say(clean)
                engine.runAndWait()
            except Exception:
                pass

        threading.Thread(target=_tts, daemon=True).start()

    def call_ollama(self, prompt: str, image_b64: Optional[str] = None, model: Optional[str] = None) -> str:
        """
        Call Ollama with keep_alive and configurable timeout.
        Retries once automatically if it times out.
        """
        target_model = model or config.model_name
        url = f"{config.ollama_host}/api/generate"
        payload_data: Dict[str, Any] = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": config.keep_alive,
        }
        if image_b64:
            payload_data["images"] = [image_b64]

        data = json.dumps(payload_data).encode("utf-8")
        timeout = float(config.timeout_seconds)

        for attempt in (1, 2):
            if self.emergency_stop:
                return "Operation aborted by user."
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    return res.get("response", "").strip()
            except urllib.error.URLError as e:
                if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
                    if attempt == 1:
                        self.cb.get("on_chat", lambda s, t: None)(
                            "Jarvis", f"⏳ Model response timed out ({int(timeout)}s). Retrying once..."
                        )
                        time.sleep(1.0)
                        continue
                    return (
                        "⚠️ The model took too long. Try a smaller model (e.g. phi3:mini) "
                        "or increase the request timeout in Settings."
                    )
                return f"⚠️ Error contacting Ollama ({target_model}): {e}"
            except Exception as e:
                return f"⚠️ AI Generation Error: {e}"

        return "⚠️ Request could not be completed after retry."

    def describe_current_screen(self) -> None:
        """Takes a screenshot, updates thumbnail, and asks vision model to describe it."""
        def _task():
            self.cb.get("on_status", lambda s: None)("Looking at screen")
            # Step 1: Capture screenshot
            sc_res = self.screen_tool.execute(resize=True)
            if not sc_res.success:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"Failed to grab screenshot: {sc_res.content}")
                self.cb.get("on_status", lambda s: None)("Idle")
                return

            raw_png = base64.b64decode(sc_res.content)
            window_title = sc_res.metadata.get("active_window", "Desktop")
            self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

            # Step 2: Query vision model
            self.cb.get("on_status", lambda s: None)("Thinking")
            vision_reply = self.call_ollama(
                prompt="Describe everything you see on this screen in detail. List the active application, visible text, and buttons.",
                image_b64=sc_res.content,
                model=config.vision_model,
            )

            msg = f"🖥️ **Active Window**: {window_title}\n\n{vision_reply}"
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", msg)
            self._speak("Here is what is on your screen, sir.")
            self.cb.get("on_status", lambda s: None)("Idle")

        threading.Thread(target=_task, daemon=True).start()

    def start_task(self, user_goal: str) -> None:
        """Start task processing in a dedicated background thread."""
        if self.emergency_stop:
            self.emergency_stop = False
            self.action_tool.execute(action="reset_steps")

        def _runner():
            try:
                self._run_task_pipeline(user_goal)
            finally:
                self.cb.get("on_task_done", lambda: None)()
                if not self.emergency_stop:
                    self.cb.get("on_status", lambda s: None)("Idle")

        self.active_task_thread = threading.Thread(target=_runner, daemon=True)
        self.active_task_thread.start()

    def _run_task_pipeline(self, user_goal: str) -> None:
        reset_step_counter()
        self.cb.get("on_chat", lambda s, t: None)("You", user_goal)

        # 1. Look at screen
        self.cb.get("on_status", lambda s: None)("Looking at screen")
        sc_res = self.screen_tool.execute(resize=True)
        if not sc_res.success:
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"Screenshot capture failed: {sc_res.content}")
            return

        raw_png = base64.b64decode(sc_res.content)
        window_title = sc_res.metadata.get("active_window", "Desktop")
        self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

        # 2. Vision summary
        self.cb.get("on_status", lambda s: None)("Thinking")
        screen_summary = self.call_ollama(
            prompt="Summarise what is currently open and visible on this screen in 2 sentences.",
            image_b64=sc_res.content,
            model=config.vision_model,
        )

        if self.emergency_stop:
            return

        # 3. Formulate Plan
        plan_prompt = (
            f"You are Jarvis, an autonomous computer assistant.\n"
            f"The user wants: '{user_goal}'\n"
            f"Active Window: '{window_title}'\n"
            f"Screen summary:\n{screen_summary}\n\n"
            f"Provide a numbered 2 to 4 step plan to achieve this goal on Windows."
        )
        plan_text = self.call_ollama(plan_prompt)

        # Check if plan contains risky keywords
        is_risky = any(crit in user_goal.lower() or crit in plan_text.lower() for crit in _CRITICAL_ACTIONS)

        # Present plan to GUI card
        self.cb.get("on_status", lambda s: None)("Waiting for your approval")
        self.cb.get("on_plan", lambda p, r: None)(plan_text, is_risky)
        self._speak("I have formulated a plan. Please approve or cancel on screen.")

        # Wait for user click on [APPROVE] or [CANCEL]
        self.plan_approval_event.clear()
        self.plan_approval_event.wait()

        if self.emergency_stop or not self.plan_approved:
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", "❌ Plan was cancelled or rejected by user.")
            self._log_action(0, "plan_review", "Plan rejected by user", False)
            return

        self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"✅ Plan approved. Executing task: '{user_goal}'")

        # 4. Multi-step Execution Loop (max_steps limit)
        step_num = 0
        while step_num < config.max_steps:
            if self.emergency_stop:
                break

            step_num += 1
            self.cb.get("on_status", lambda s: None)("Thinking")

            decide_prompt = (
                f"You are an assistant controlling a Windows PC.\n"
                f"Goal: '{user_goal}'\n"
                f"Active Window: '{window_title}'\n"
                f"Current screen description: {screen_summary}\n\n"
                f"Decide the NEXT SINGLE action.\n"
                f"Answer ONLY in this JSON format:\n"
                f'{{"action": "open_app"|"hotkey"|"type"|"click"|"scroll"|"finish", "text": "...", "keys": ["ctrl", "..."], "x": 0, "y": 0, "explanation": "..."}}'
            )
            decision_raw = self.call_ollama(decide_prompt)
            if self.emergency_stop:
                break

            # Parse JSON decision
            parsed: Dict[str, Any] = {}
            try:
                m = re.search(r"\{.*\}", decision_raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
            except Exception:
                pass

            act_type = parsed.get("action", "").lower().strip()
            explanation = parsed.get("explanation", decision_raw[:120])

            if not act_type or act_type == "finish":
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"🏁 Task completed: {explanation}")
                self._speak("Task completed, sir.")
                self._log_action(step_num, "finish", explanation, True)
                break

            # Check if this specific action step requires approval
            step_is_critical = any(crit in explanation.lower() or crit in str(parsed.get("text", "")).lower() for crit in _CRITICAL_ACTIONS)
            if config.ask_before_every_action or step_is_critical:
                self.cb.get("on_status", lambda s: None)("Waiting for your approval")
                step_desc = f"Step {step_num}: Action '{act_type}' ({explanation})"
                self.cb.get("on_plan", lambda p, r: None)(step_desc, step_is_critical)
                self.step_approval_event.clear()
                self.step_approval_event.wait()

                if self.emergency_stop or not self.step_approved:
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"🛑 Step {step_num} was rejected by user.")
                    self._log_action(step_num, act_type, "Step rejected by user", False)
                    break

            # Execute action
            self.cb.get("on_status", lambda s: None)("Acting")
            parsed["dry_run"] = config.dry_run
            res = self.action_tool.execute(**parsed)
            self._log_action(step_num, act_type, res.content, res.success)

            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"👉 **Step {step_num}** ({act_type}): {res.content}")

            if not res.success:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"⚠️ Action stopped: {res.content}")
                break

            time.sleep(1.2)

            # Re-verify screen after action
            self.cb.get("on_status", lambda s: None)("Looking at screen")
            sc_res = self.screen_tool.execute(resize=True)
            if sc_res.success:
                raw_png = base64.b64decode(sc_res.content)
                window_title = sc_res.metadata.get("active_window", "Desktop")
                self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

        if step_num >= config.max_steps:
            self.cb.get("on_chat", lambda s, t: None)(
                "Jarvis", f"⚠️ Maximum {config.max_steps} steps reached for this task. Pausing."
            )
            self._speak("Maximum steps reached. Pausing for instructions.")

    def approve_plan(self, approved: bool) -> None:
        """Called by GUI buttons [APPROVE] or [CANCEL]."""
        self.plan_approved = approved
        self.step_approved = approved
        self.plan_approval_event.set()
        self.step_approval_event.set()

    def record_voice(self, on_text_received: Callable[[str], None]) -> None:
        """Push-to-talk voice recording in a background thread."""
        def _listen():
            self.cb.get("on_status", lambda s: None)("Listening")
            try:
                import speech_recognition as sr
                r = sr.Recognizer()
                r.energy_threshold = 300
                r.dynamic_energy_threshold = False
                r.pause_threshold = 0.8
                with sr.Microphone() as source:
                    audio = r.listen(source, timeout=8, phrase_time_limit=12)
                    self.cb.get("on_status", lambda s: None)("Thinking")
                    text = r.recognize_google(audio)
                    if text:
                        on_text_received(text.strip())
            except Exception as e:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"🎙️ Microphone note: {e}")
            finally:
                self.cb.get("on_status", lambda s: None)("Idle")

        threading.Thread(target=_listen, daemon=True).start()
