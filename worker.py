"""
worker.py — Robust Background Execution Engine for Jarvis.
Features:
  1. Fast-Path Autonomous Execution: Instant YouTube search/play, app launch (Notepad, Chrome, Calc, Calendar), meeting creation.
  2. Robust Model Action Parser: Extracts action commands via regex even if LLM JSON is malformed or truncated.
  3. Ollama keep_alive & timeout resilience.
  4. Real-time screen capture and vision analysis via moondream.
  5. Continuous and push-to-talk microphone listening.
  6. Global emergency stop via Ctrl+Alt+Q and mouse failsafe.
"""

from __future__ import annotations

import base64
import ctypes
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
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

_CRITICAL_ACTIONS = [
    "send message", "send email", "delete file", "delete folder",
    "remove", "rm", "purchase", "buy", "pay", "payment",
    "close unsaved", "shutdown", "reboot", "format"
]

_LOG_FILE = os.path.join(_REPO_ROOT, "computer_actions.log")


class JarvisWorker:
    """Manages asynchronous task execution without freezing the UI."""

    def __init__(self, callbacks: Dict[str, Callable[..., Any]]) -> None:
        self.cb = callbacks
        self.emergency_stop = False
        self.active_task_thread: Optional[threading.Thread] = None

        self.plan_approval_event = threading.Event()
        self.plan_approved = False

        self.step_approval_event = threading.Event()
        self.step_approved = False

        self.screen_tool = ScreenCaptureTool()
        self.describe_tool = DescribeScreenTool()
        self.action_tool = ComputerActionTool()

        self._exit_listener = False
        self._is_speaking = False
        self.hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        self.hotkey_thread.start()

        # Always-on Background Voice Listener (Listens even when minimized or in background!)
        self.bg_mic_thread = threading.Thread(target=self._bg_voice_listener, daemon=True)
        self.bg_mic_thread.start()

    def _bg_voice_listener(self) -> None:
        """
        Continuous background microphone listener that listens for 'Hey Jarvis' or 'Jarvis'
        even when the window is minimized or behind other applications.
        """
        try:
            import speech_recognition as sr
        except ImportError:
            return

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = False
        recognizer.pause_threshold = 0.8
        recognizer.phrase_threshold = 0.2
        recognizer.non_speaking_duration = 0.4

        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.8)
                recognizer.energy_threshold = max(35.0, min(recognizer.energy_threshold, 65.0))
        except Exception:
            recognizer.energy_threshold = 150.0

        wake_regex = re.compile(
            r'\b(hey|hay|hi|hello|ok|yo|ai|wake\s+up)?\s*(jarvis|javis|jarves|jervis|travis|service|chavez|jar|java)\b',
            re.IGNORECASE
        )

        is_awake = False
        awake_until = 0.0

        while not self._exit_listener:
            if self._is_speaking or self.emergency_stop:
                time.sleep(0.3)
                continue

            try:
                with sr.Microphone() as source:
                    audio = recognizer.listen(source, timeout=4, phrase_time_limit=9)
            except Exception:
                continue

            if self._is_speaking or self.emergency_stop:
                continue

            try:
                text = recognizer.recognize_google(audio).strip()
            except Exception:
                continue

            if not text:
                continue

            lower = text.lower().strip()

            # Check if previous awake window expired
            if is_awake and time.time() > awake_until:
                is_awake = False

            # Case 1: Wake word detected (e.g. "Hey Jarvis open notepad" or just "Hey Jarvis")
            if wake_regex.search(lower):
                rest = wake_regex.sub('', lower).strip(" ,:!?.")
                rest = re.sub(r'^(?:and|also|then|please|can you|could you|now)\s+', '', rest).strip()
                if not rest:
                    # User said only "Hey Jarvis"
                    is_awake = True
                    awake_until = time.time() + 25.0
                    self.cb.get("on_status", lambda s: None)("Listening")
                    self.cb.get("on_chat", lambda s, t: None)("You", text)
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", "Yes, sir? How may I assist you?")
                    self._speak("Yes, sir? How may I assist you?")
                else:
                    # User said "Hey Jarvis [command]" in one breath
                    is_awake = True
                    awake_until = time.time() + 25.0
                    self.start_task(rest)
                continue

            # Case 2: Already awake within the 25-second window -> direct command
            if is_awake:
                awake_until = time.time() + 25.0
                self.start_task(lower)

    def _hotkey_listener(self) -> None:
        """Global emergency stop listener: Ctrl+Alt+Q."""
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
        line = f"[{ts}] [step={step}] ACTION: {action} | RESULT: {result} | SUCCESS: {success}\n"
        try:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
        self.cb.get("on_log", lambda *args: None)(ts, step, action, result, success)

    def _speak(self, text: str) -> None:
        """Speak response if voice is enabled in config."""
        if not config.voice_enabled or not text:
            return

        def _tts():
            self._is_speaking = True
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", 180)
                clean = re.sub(r"[*_#`•<>]", "", text)
                clean = re.sub(r"https?://\S+", "", clean).strip()
                if clean:
                    engine.say(clean)
                    engine.runAndWait()
            except Exception:
                pass
            finally:
                time.sleep(0.3)
                self._is_speaking = False

        threading.Thread(target=_tts, daemon=True).start()

    def call_ollama(self, prompt: str, image_b64: Optional[str] = None, model: Optional[str] = None) -> str:
        """Call Ollama with keep_alive and timeout retry."""
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
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    return res.get("response", "").strip()
            except urllib.error.URLError as e:
                if attempt == 1:
                    time.sleep(1.0)
                    continue
                return f"Error: timed out ({int(timeout)}s)"
            except Exception as e:
                return f"Error: {e}"

        return "Error: timed out"

    # ─────────────────────────────────────────────────────────────
    #  SMART FAST-PATH TASK RESOLVER  (v2 — extended patterns)
    # ─────────────────────────────────────────────────────────────
    def _try_fast_path(self, goal: str) -> Optional[str]:
        """
        Immediately handles common tasks WITHOUT calling the LLM.
        Covers: YouTube, app launch, website open, meeting schedule, screen inspect,
                volume, brightness, weather, Wikipedia lookup, calculator.
        Returns a reply string on success, None to fall through to LLM.
        """
        raw = goal.strip()
        lower = raw.lower()
        # Strip common preambles so "hey jarvis open notepad" → "open notepad"
        lower_clean = re.sub(
            r"^(?:please|can you|could you|jarvis|hey jarvis|ok jarvis|hi jarvis|and|also)\s+",
            "", lower
        ).strip()

        # ── 1. YOUTUBE ────────────────────────────────────────────
        # Triggers: "play X", "play X on youtube", "open youtube and play X",
        #           "search youtube for X", "watch X on youtube",
        #           "player X video" (typo), "open youtube"
        yt_keywords = ("youtube" in lower_clean)
        play_keywords = any(w in lower_clean for w in ("play ", "player ", "watch ", "search youtube"))

        # Explicit "play <query>" pattern
        yt_match = re.search(
            r"(?:open\s+youtube\s+(?:and\s+)?(?:play|search)|play(?:er)?|watch|search\s+youtube\s+for)\s+"
            r"([a-zA-Z0-9\s_\-\'\!\.]+?)(?:\s+on\s+youtube|\s+(?:recent|latest|new)\s+video|s?\s*video|$)",
            lower_clean,
        )
        if yt_match or (yt_keywords and play_keywords):
            if yt_match:
                query = yt_match.group(1).strip()
            else:
                # Fallback: strip everything before play/watch keyword
                query = re.sub(r".*?(?:play(?:er)?|watch|search youtube for)\s+", "", lower_clean)
                query = re.sub(r"\s+on\s+youtube.*$", "", query).strip()
            if not query or query in ("youtube", "video", "videos"):
                # Just open YouTube homepage
                subprocess.Popen('explorer.exe "https://www.youtube.com"', shell=True)
                self._log_action(1, "open_youtube", "Opened YouTube homepage", True)
                return "Opening YouTube for you, sir!"
            enc = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={enc}"
            subprocess.Popen(f'explorer.exe "{url}"', shell=True)
            msg = f"🎬 Opening YouTube and searching for **'{query}'** right away, sir!"
            self._log_action(1, "open_youtube", f"YouTube search: {query}", True)
            return msg

        # ── 2. OPEN APP / WEBSITE ─────────────────────────────────
        # Triggers: "open notepad", "launch chrome", "start calculator",
        #           "open google.com", "go to amazon", "visit reddit"
        open_match = re.search(
            r"^(?:open|launch|start|run|go to|visit|navigate to)\s+(.+)$", lower_clean
        )
        if open_match:
            target = open_match.group(1).strip().lower()
            app_map = {
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "calc": "calc.exe",
                "chrome": "chrome.exe",
                "google chrome": "chrome.exe",
                "edge": "msedge.exe",
                "microsoft edge": "msedge.exe",
                "firefox": "firefox.exe",
                "browser": "https://www.google.com",
                "youtube": "https://www.youtube.com",
                "google": "https://www.google.com",
                "gmail": "https://mail.google.com",
                "calendar": "outlookcal:",
                "google calendar": "https://calendar.google.com",
                "outlook": "outlook.exe",
                "settings": "ms-settings:",
                "control panel": "control.exe",
                "file explorer": "explorer.exe",
                "files": "explorer.exe",
                "cmd": "cmd.exe",
                "command prompt": "cmd.exe",
                "terminal": "wt.exe",
                "powershell": "powershell.exe",
                "word": "winword.exe",
                "excel": "excel.exe",
                "powerpoint": "powerpnt.exe",
                "paint": "mspaint.exe",
                "task manager": "taskmgr.exe",
                "spotify": "spotify.exe",
                "discord": "discord.exe",
                "teams": "msteams.exe",
                "zoom": "zoom.exe",
                "whatsapp": "whatsapp.exe",
                "amazon": "https://www.amazon.com",
                "reddit": "https://www.reddit.com",
                "twitter": "https://www.twitter.com",
                "x": "https://www.x.com",
                "facebook": "https://www.facebook.com",
                "instagram": "https://www.instagram.com",
                "netflix": "https://www.netflix.com",
                "github": "https://www.github.com",
                "chatgpt": "https://chat.openai.com",
                "maps": "https://maps.google.com",
                "google maps": "https://maps.google.com",
                "translate": "https://translate.google.com",
            }
            # Look up exact match first
            cmd = app_map.get(target)
            if not cmd:
                # Website pattern: "open amazon.com", "open github.com"
                url_m = re.match(r"^([\w\-]+\.[a-z]{2,})(/.*)?$", target)
                if url_m:
                    cmd = f"https://{target}"
            if cmd:
                if cmd.startswith("http"):
                    subprocess.Popen(f'explorer.exe "{cmd}"', shell=True)
                elif ":" in cmd and not cmd.endswith(".exe"):
                    # ms-settings: or outlookcal: style URI
                    subprocess.Popen(f'explorer.exe {cmd}', shell=True)
                else:
                    subprocess.Popen(cmd, shell=True)
                msg = f"✅ Opening **{target.title()}** for you, sir!"
                self._log_action(1, "open_app", f"Launched: {cmd}", True)
                return msg

        # ── 3. MEETING / SCHEDULE ─────────────────────────────────
        if any(w in lower_clean for w in ("meeting", "schedule", "appointment", "set a reminder", "remind me")):
            title_m = re.search(r"(?:with|for|about)\s+([a-zA-Z0-9\s]+?)(?:\s+at|\s+on|\s+tomorrow|\s+today|$)", lower_clean)
            title = f"Meeting - {title_m.group(1).strip().title()}" if title_m else "New Meeting"
            enc_title = urllib.parse.quote_plus(title)
            cal_url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={enc_title}"
            subprocess.Popen(f'explorer.exe "{cal_url}"', shell=True)
            msg = f"📅 Scheduling **{title}**! Opening Google Calendar for you, sir."
            self._log_action(1, "schedule_meeting", f"Calendar opened for: {title}", True)
            return msg

        # ── 4. SCREEN DESCRIBE ───────────────────────────────────
        if any(p in lower_clean for p in [
            "what is on my screen", "what's on my screen", "whats on my screen",
            "describe screen", "describe my screen", "look at my screen",
            "summarise screen", "summarize screen", "summarise this page", "summarize this page",
            "what do you see", "what can you see"
        ]):
            self.describe_current_screen()
            return "ANALYZING_SCREEN"

        # ── 5. VOLUME CONTROLS ───────────────────────────────────
        if re.search(r"(?:volume|sound)\s+(?:up|louder|increase)", lower_clean):
            subprocess.Popen(
                'python -c "import ctypes; from ctypes import wintypes; '
                'import comtypes; from comtypes import CLSCTX_ALL; '
                'from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume; '
                'print(\'volume up\')"', shell=True
            )
            # Fallback: use keyboard shortcut
            import pyautogui
            for _ in range(5):
                pyautogui.press("volumeup")
            return "🔊 Volume increased, sir!"

        if re.search(r"(?:volume|sound)\s+(?:down|lower|decrease|mute|quiet)", lower_clean):
            if "mute" in lower_clean:
                import pyautogui
                pyautogui.press("volumemute")
                return "🔇 Muted, sir!"
            import pyautogui
            for _ in range(5):
                pyautogui.press("volumedown")
            return "🔉 Volume lowered, sir!"

        # ── 6. QUICK SEARCH (Google) ─────────────────────────────
        search_m = re.search(r"^(?:search|google|look up|find)\s+(.+)$", lower_clean)
        if search_m:
            query = search_m.group(1).strip()
            enc = urllib.parse.quote_plus(query)
            subprocess.Popen(f'explorer.exe "https://www.google.com/search?q={enc}"', shell=True)
            msg = f"🔍 Searching Google for **'{query}'**, sir!"
            self._log_action(1, "google_search", f"Searched: {query}", True)
            return msg

        # ── 7. WIKIPEDIA QUICK LOOKUP ────────────────────────────
        wiki_m = re.search(r"^(?:wikipedia|wiki)\s+(.+)$", lower_clean)
        if wiki_m:
            query = wiki_m.group(1).strip()
            enc = urllib.parse.quote_plus(query)
            subprocess.Popen(f'explorer.exe "https://en.wikipedia.org/wiki/Special:Search/{enc}"', shell=True)
            return f"📖 Opening Wikipedia page for **'{query}'**, sir!"

        # ── 8. SCREENSHOT ────────────────────────────────────────
        if any(p in lower_clean for p in ["take a screenshot", "take screenshot", "capture screen", "screenshot"]):
            self.describe_current_screen()
            return "ANALYZING_SCREEN"

        return None  # No fast-path match → fall through to LLM

    def describe_current_screen(self) -> None:
        """Capture screenshot and analyze with vision model."""
        def _task():
            self.cb.get("on_status", lambda s: None)("Looking at screen")
            sc_res = self.screen_tool.execute(resize=True)
            if not sc_res.success:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"Screenshot capture failed: {sc_res.content}")
                self.cb.get("on_status", lambda s: None)("Idle")
                return

            raw_png = base64.b64decode(sc_res.content)
            window_title = sc_res.metadata.get("active_window", "Desktop")
            self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

            self.cb.get("on_status", lambda s: None)("Thinking")
            vision_reply = self.call_ollama(
                prompt="Describe everything visible on this screen in detail. List the active application, visible text, buttons, and content.",
                image_b64=sc_res.content,
                model=config.vision_model,
            )

            msg = f"🖥️ **Active Window**: {window_title}\n\n{vision_reply}"
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", msg)
            self._speak("Here is what is on your screen, sir.")
            self.cb.get("on_status", lambda s: None)("Idle")

        threading.Thread(target=_task, daemon=True).start()

    def start_task(self, user_goal: str) -> None:
        """Execute a task in the background."""
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

        # FAST PATH CHECK: Handles YouTube, App Launches, and Meetings in < 0.5s!
        fast_result = self._try_fast_path(user_goal)
        if fast_result:
            if fast_result != "ANALYZING_SCREEN":
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", fast_result)
                self._speak(fast_result)
            return

        # Fallback to Autonomous Multi-step LLM Loop
        self.cb.get("on_status", lambda s: None)("Looking at screen")
        sc_res = self.screen_tool.execute(resize=True)
        if not sc_res.success:
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"Screenshot capture failed: {sc_res.content}")
            return

        raw_png = base64.b64decode(sc_res.content)
        window_title = sc_res.metadata.get("active_window", "Desktop")
        self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

        # Plan formulation
        self.cb.get("on_status", lambda s: None)("Thinking")
        plan_prompt = (
            f"You are Jarvis, an autonomous computer assistant.\n"
            f"Goal: '{user_goal}'\n"
            f"Active Window: '{window_title}'\n\n"
            f"Provide a numbered 2 to 3 step plan to achieve this goal on Windows."
        )
        plan_text = self.call_ollama(plan_prompt)
        if "Error:" in plan_text:
            plan_text = f"1. Open target application for '{user_goal}'\n2. Perform required typing or mouse actions\n3. Verify result"

        is_risky = any(crit in user_goal.lower() or crit in plan_text.lower() for crit in _CRITICAL_ACTIONS)

        # Request user approval via Plan Card
        self.cb.get("on_status", lambda s: None)("Waiting for your approval")
        self.cb.get("on_plan", lambda p, r: None)(plan_text, is_risky)
        self._speak("I have a plan. Please approve or cancel on screen.")

        self.plan_approval_event.clear()
        self.plan_approval_event.wait()

        if self.emergency_stop or not self.plan_approved:
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", "❌ Plan cancelled by user.")
            return

        self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"✅ Plan approved. Starting execution...")

        # Action Execution Loop
        step_num = 0
        while step_num < config.max_steps:
            if self.emergency_stop:
                break
            step_num += 1

            self.cb.get("on_status", lambda s: None)("Thinking")
            decide_prompt = (
                f"Goal: '{user_goal}'. Active Window: '{window_title}'.\n"
                f"Decide the NEXT action.\n"
                f"Reply in format:\n"
                f"ACTION: open_app | type | click | hotkey | scroll | finish\n"
                f"TEXT: <text to type or app name>\n"
                f"EXPLANATION: <brief reason>"
            )
            raw = self.call_ollama(decide_prompt)
            if self.emergency_stop:
                break

            # Robust Regex Parser (Extracts parameters even if LLM output is malformed)
            act_match = re.search(r"(?:ACTION|action)[\s\":=]+([a-zA-Z_]+)", raw)
            text_match = re.search(r"(?:TEXT|text)[\s\":=]+([^\n\r\"}]+)", raw)
            exp_match = re.search(r"(?:EXPLANATION|explanation)[\s\":=]+([^\n\r\"}]+)", raw)

            act_type = act_match.group(1).lower().strip() if act_match else ""
            act_text = text_match.group(1).strip() if text_match else ""
            explanation = exp_match.group(1).strip() if exp_match else "Executing step"

            # Fallback heuristic if regex failed
            if not act_type or act_type in ["none", "finish", "done"]:
                if "type" in raw.lower() and act_text:
                    act_type = "type"
                elif "open" in raw.lower() and act_text:
                    act_type = "open_app"
                else:
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"🏁 Task complete: {explanation}")
                    self._speak("Task complete, sir.")
                    break

            # Action execution
            self.cb.get("on_status", lambda s: None)("Acting")
            res = self.action_tool.execute(
                action=act_type,
                text=act_text,
                dry_run=config.dry_run
            )
            self._log_action(step_num, act_type, res.content, res.success)
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"👉 **Step {step_num}** ({act_type}): {res.content}")

            if not res.success:
                break

            time.sleep(1.2)

            # Re-capture screen
            self.cb.get("on_status", lambda s: None)("Looking at screen")
            sc_res = self.screen_tool.execute(resize=True)
            if sc_res.success:
                raw_png = base64.b64decode(sc_res.content)
                window_title = sc_res.metadata.get("active_window", "Desktop")
                self.cb.get("on_screenshot", lambda b, w: None)(raw_png, window_title)

    def approve_plan(self, approved: bool) -> None:
        self.plan_approved = approved
        self.step_approved = approved
        self.plan_approval_event.set()
        self.step_approval_event.set()

    def record_voice(self, on_text_received: Callable[[str], None]) -> None:
        """Push-to-talk microphone recording."""
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
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"🎙️ Mic note: {e}")
            finally:
                self.cb.get("on_status", lambda s: None)("Idle")

        threading.Thread(target=_listen, daemon=True).start()
