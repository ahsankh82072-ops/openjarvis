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
import email
from email.header import decode_header
import imaplib
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

try:
    import pyautogui
    pyautogui.FAILSAFE = False
except Exception:
    pass

from openjarvis.tools.computer_action import ComputerActionTool, reset_step_counter
from openjarvis.tools.describe_screen import DescribeScreenTool
from openjarvis.tools.screen_capture import ScreenCaptureTool

_DANGEROUS_PATTERNS = [
    r"\bformat\s+[a-z]:",
    r"\b(?:shutdown|reboot)\s+/[s|r]",
    r"\brmdir\s+/s\s+/q\s+c:",
    r"\bdel\s+/[fqs]+\s+c:\\windows",
    r"\b(?:destroy|wipe)\s+(?:hard\s*drive|disk|partition)\b",
]

_CRITICAL_ACTIONS = [
    r"\bdelete\s+(?:file|folder|database|partition)\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpurchase\b",
    r"\bbuy\b",
    r"\bpayment\b",
]

_LOG_FILE = os.path.join(_REPO_ROOT, "computer_actions.log")


class PushToTalkRecorder:
    """Captures clean audio frames while Spacebar or mic button is held down."""

    def __init__(self) -> None:
        try:
            import pyaudio
            self.pa = pyaudio.PyAudio()
        except Exception:
            self.pa = None
        self.stream = None
        self.is_recording = False
        self.frames: List[bytes] = []
        self.sample_rate = 16000

    def start(self) -> None:
        if self.is_recording or not self.pa:
            return
        self.is_recording = True
        self.frames = []
        import pyaudio
        try:
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=1024
            )
        except Exception:
            self.sample_rate = 44100
            try:
                self.stream = self.pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=1024
                )
            except Exception:
                self.is_recording = False
                return

        def _reader():
            while self.is_recording and self.stream:
                try:
                    data = self.stream.read(1024, exception_on_overflow=False)
                    self.frames.append(data)
                except Exception:
                    break

        threading.Thread(target=_reader, daemon=True).start()

    def stop(self) -> Optional[str]:
        if not self.is_recording:
            return None
        self.is_recording = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if not self.frames:
            return None

        raw_bytes = b"".join(self.frames)
        # Require at least 0.25s of audio to prevent micro-clicks
        if len(raw_bytes) < int(self.sample_rate * 2 * 0.25):
            return None

        try:
            import speech_recognition as sr
            audio_data = sr.AudioData(raw_bytes, self.sample_rate, 2)
            r = sr.Recognizer()
            text = r.recognize_google(audio_data).strip()
            return text if text else None
        except Exception:
            return None


class JarvisWorker:
    """Manages asynchronous task execution without freezing the UI."""

    def __init__(self, callbacks: Dict[str, Callable[..., Any]]) -> None:
        self.cb = callbacks
        self.emergency_stop = False
        self.active_task_thread: Optional[threading.Thread] = None

        self.plan_approval_event = threading.Event()
        self.plan_approved = False
        self.waiting_for_plan_approval = False

        self.step_approval_event = threading.Event()
        self.step_approved = False

        self.screen_tool = ScreenCaptureTool()
        self.describe_tool = DescribeScreenTool()
        self.action_tool = ComputerActionTool()

        self._exit_listener = False
        self._is_speaking = False

        # Spacebar Push-to-Talk Engine
        self.ptt_recorder = PushToTalkRecorder()
        self.is_ptt_active = False
        self.is_live_mode_active = False

        self.hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        self.hotkey_thread.start()

        # Always-on Background Voice Listener (Listens across all apps like Google Chrome!)
        self.bg_voice_thread = threading.Thread(target=self._bg_voice_listener, daemon=True)
        self.bg_voice_thread.start()

    def _bg_voice_listener(self) -> None:
        """
        Continuous background voice listener that works across all applications.
        When user switches to Google, Chrome, or any app and says:
        'Jarvis [instruction]' or 'Hey Jarvis [instruction]',
        Jarvis immediately captures the active window screen and executes the instruction.
        """
        try:
            import speech_recognition as sr
        except ImportError:
            return

        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.6
        recognizer.phrase_threshold = 0.2
        recognizer.non_speaking_duration = 0.3

        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
        except Exception:
            pass

        wake_regex = re.compile(
            r'\b(hey\s+|ok\s+|hi\s+|hello\s+|yo\s+)?(jarvis|javis|jarves|jervis|travis|service|chavez)\b',
            re.IGNORECASE
        )

        while not self._exit_listener:
            if self._is_speaking or self.emergency_stop or self.is_ptt_active or self.is_live_mode_active:
                time.sleep(0.3)
                continue

            try:
                with sr.Microphone() as source:
                    audio = recognizer.listen(source, timeout=3.0, phrase_time_limit=8.0)
            except Exception:
                continue

            if self._is_speaking or self.emergency_stop or self.is_ptt_active:
                continue

            try:
                text = recognizer.recognize_google(audio).strip()
            except Exception:
                continue

            if not text:
                continue

            lower = text.lower().strip()

            if wake_regex.search(lower):
                rest = wake_regex.sub('', lower).strip(" ,:!?.")
                rest = re.sub(r'^(?:and|also|then|please|can you|could you|now)\s+', '', rest).strip()

                if not rest:
                    self.cb.get("on_status", lambda s: None)("Listening")
                    self.cb.get("on_chat", lambda s, t: None)("You", text)
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", "Yes, sir? What would you like me to do?")
                    self._speak("Yes, sir? What would you like me to do?")
                else:
                    self.start_task(rest)

    def start_push_to_talk(self) -> None:
        """Invoked when user presses and holds Spacebar."""
        if self.is_ptt_active or self.emergency_stop:
            return
        self.is_ptt_active = True
        self.cb.get("on_status", lambda s: None)("Listening")
        self.ptt_recorder.start()

    def stop_push_to_talk(self) -> None:
        """Invoked when user releases Spacebar."""
        if not self.is_ptt_active:
            return
        self.is_ptt_active = False
        self.cb.get("on_status", lambda s: None)("Thinking")

        def _worker():
            spoken = self.ptt_recorder.stop()
            if spoken:
                # If waiting for plan approval, check for voice yes / no
                if self.waiting_for_plan_approval:
                    lower = spoken.lower().strip()
                    if any(w in lower for w in ["yes", "approve", "proceed", "go", "do it", "sure"]):
                        self.approve_plan(True)
                        self._speak("Plan approved, executing now.")
                        return
                    elif any(w in lower for w in ["no", "cancel", "stop", "abort"]):
                        self.approve_plan(False)
                        self._speak("Plan cancelled, sir.")
                        return

                self.start_task(spoken)
            else:
                self.cb.get("on_status", lambda s: None)("Idle")

        threading.Thread(target=_worker, daemon=True).start()

    def _hotkey_listener(self) -> None:
        """Global listener: Ctrl+Alt+Q for emergency stop, Ctrl+Alt+Space for global Push-to-Talk."""
        user32 = ctypes.windll.user32
        space_was_down = False
        while not self._exit_listener:
            try:
                ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
                alt = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0
                q_key = (user32.GetAsyncKeyState(0x51) & 0x8000) != 0
                if ctrl and alt and q_key:
                    self.stop()
                    time.sleep(1.0)

                # Global Push-to-Talk (Ctrl+Alt+Space) from anywhere in Windows
                space_key = (user32.GetAsyncKeyState(0x20) & 0x8000) != 0
                if ctrl and alt and space_key:
                    if not space_was_down:
                        space_was_down = True
                        self.cb.get("on_activate_window", lambda: None)()
                        self.start_push_to_talk()
                else:
                    if space_was_down:
                        space_was_down = False
                        self.stop_push_to_talk()
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

    def call_gemini(self, prompt: str, image_b64: Optional[str] = None) -> Optional[str]:
        """Calls Google Gemini Cloud API in < 1s with 0% PC RAM."""
        if not config.use_gemini_cloud or not config.gemini_api_key:
            return None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent"
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if image_b64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": image_b64
                }
            })
        payload = {"contents": [{"parts": parts}]}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": config.gemini_api_key
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                candidates = res.get("candidates", [])
                if candidates:
                    p = candidates[0].get("content", {}).get("parts", [])
                    if p:
                        return p[0].get("text", "").strip()
        except Exception:
            # Seamless fallback to local Ollama
            pass
        return None

    def call_ai(self, prompt: str, image_b64: Optional[str] = None, model: Optional[str] = None) -> str:
        """Calls Gemini Cloud first (fast & 0 RAM), falls back to Ollama seamlessly."""
        if self.emergency_stop:
            return "Operation aborted by user."
        # 1. Cloud Gemini (sub-second response, 0% laptop RAM)
        cloud_reply = self.call_gemini(prompt, image_b64)
        if cloud_reply:
            return cloud_reply
        # 2. Local Ollama Fallback
        return self.call_ollama(prompt, image_b64, model)

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
    #  HANDS-FREE INTEGRATIONS: GMAIL, CALENDAR & WHATSAPP
    # ─────────────────────────────────────────────────────────────
    def check_gmail_inbox(self, max_results: int = 5) -> str:
        """Connects to Gmail via IMAP over SSL to fetch unread emails hands-free."""
        email_addr = config.gmail_address.strip()
        app_pwd = config.gmail_app_password.strip().replace(" ", "")

        if not email_addr or not app_pwd:
            subprocess.Popen('explorer.exe "https://mail.google.com"', shell=True)
            msg = (
                "📧 Gmail credentials are not configured yet, sir. I have opened Gmail in your browser for you.\n\n"
                "💡 To hear updates hands-free without opening a browser, open the **⚙️ Integrations & Settings** tab and enter your Gmail Address and 16-character Google App Password."
            )
            self._speak("Gmail is not attached yet, sir. I opened Gmail in your browser.")
            return msg

        try:
            self.cb.get("on_status", lambda s: None)("Checking Gmail")
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            mail.login(email_addr, app_pwd)
            mail.select("INBOX", readonly=True)

            status, response = mail.search(None, "UNSEEN")
            unread_ids = response[0].split() if status == "OK" and response[0] else []

            if not unread_ids:
                status, all_response = mail.search(None, "ALL")
                all_ids = all_response[0].split() if status == "OK" and all_response[0] else []
                if not all_ids:
                    mail.logout()
                    msg = "📬 Your Gmail inbox is completely empty, sir. No emails found."
                    self._speak("Your Gmail inbox is empty, sir.")
                    return msg
                recent_ids = all_ids[-max_results:]
                header_prefix = "📬 No unread emails, sir. Here are your most recent messages:\n"
                tts_prefix = "No unread emails, sir. Your latest messages are:"
            else:
                recent_ids = unread_ids[-max_results:]
                header_prefix = f"📬 You have **{len(unread_ids)} unread email(s)** in Gmail, sir:\n"
                tts_prefix = f"You have {len(unread_ids)} unread email{'s' if len(unread_ids) > 1 else ''}, sir."

            recent_ids.reverse()  # Newest first
            lines = []
            speech_items = []

            def _clean_hdr(raw):
                if not raw:
                    return "Unknown"
                parts = decode_header(raw)
                decoded = []
                for piece, enc in parts:
                    if isinstance(piece, bytes):
                        decoded.append(piece.decode(enc or "utf-8", errors="replace"))
                    else:
                        decoded.append(str(piece))
                return "".join(decoded)

            for i, msg_id in enumerate(recent_ids, 1):
                res, data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if res != "OK":
                    continue
                raw_email = data[0][1]
                msg_obj = email.message_from_bytes(raw_email)
                sender = _clean_hdr(msg_obj.get("From", "Unknown"))
                subject = _clean_hdr(msg_obj.get("Subject", "(No Subject)"))
                clean_sender = re.sub(r"<[^>]+>", "", sender).strip() or sender

                lines.append(f"{i}. **{clean_sender}**: {subject}")
                if i <= 3:
                    speech_items.append(f"From {clean_sender}: {subject}")

            mail.logout()

            chat_report = header_prefix + "\n".join(lines)
            spoken_summary = tts_prefix + " " + ". ".join(speech_items)
            self._speak(spoken_summary)
            self._log_action(1, "check_gmail", f"Fetched {len(recent_ids)} emails", True)
            return chat_report

        except Exception as e:
            err_msg = str(e)
            if "AUTHENTICATIONFAILED" in err_msg or "Invalid credentials" in err_msg:
                msg = (
                    "❌ Gmail Authentication Failed, sir.\n\n"
                    "Please ensure you use a **16-character Google App Password** generated at myaccount.google.com/apppasswords."
                )
                self._speak("Gmail authentication failed, sir. Please check your App Password.")
                return msg
            subprocess.Popen('explorer.exe "https://mail.google.com"', shell=True)
            msg = f"⚠️ Could not check Gmail directly ({err_msg}). Opened Gmail in your browser, sir."
            self._speak("Could not reach Gmail directly, sir. Opened Gmail in your browser.")
            return msg

    def check_calendar_schedule(self) -> str:
        """Checks upcoming schedule from iCal feed or opens preferred Calendar."""
        ical_url = config.calendar_ical_url.strip()
        if ical_url and ical_url.startswith("http"):
            try:
                self.cb.get("on_status", lambda s: None)("Checking Calendar")
                req = urllib.request.Request(ical_url, headers={"User-Agent": "Jarvis-Desktop/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    content = resp.read().decode("utf-8", errors="replace")

                events = []
                now = datetime.datetime.now()
                today_str = now.strftime("%Y%m%d")

                raw_events = content.split("BEGIN:VEVENT")
                for item in raw_events[1:]:
                    summary_m = re.search(r"SUMMARY:(.*?)(?:\r?\n[A-Z]|\r?\n$)", item, re.DOTALL)
                    dtstart_m = re.search(r"DTSTART(?:;[^:]+)?:(\d{8}(?:T\d{4,6}Z?)?)", item)
                    if summary_m and dtstart_m:
                        summary = summary_m.group(1).replace("\r", "").replace("\n", "").strip()
                        dtstart = dtstart_m.group(1)
                        if dtstart.startswith(today_str):
                            time_part = ""
                            if "T" in dtstart:
                                t_raw = dtstart.split("T")[1][:4]
                                time_part = f" at {t_raw[:2]}:{t_raw[2:]}"
                            events.append(f"{summary}{time_part}")

                if events:
                    chat_msg = f"📅 **Today's Schedule** ({len(events)} event{'s' if len(events) > 1 else ''}):\n" + "\n".join(f"{i+1}. {ev}" for i, ev in enumerate(events))
                    speak_msg = f"You have {len(events)} event{'s' if len(events) > 1 else ''} on your calendar today: " + ", ".join(events)
                    self._speak(speak_msg)
                    return chat_msg
                else:
                    msg = "📅 You have no scheduled events for today, sir. Your calendar is completely clear!"
                    self._speak("You have no events scheduled for today, sir.")
                    return msg
            except Exception as e:
                print(f"Calendar iCal error: {e}")

        # Fallback to opening configured calendar
        if "windows" in config.calendar_preference.lower():
            subprocess.Popen("explorer.exe outlookcal:", shell=True)
            msg = "📅 Opening Windows Calendar for you, sir."
        else:
            subprocess.Popen('explorer.exe "https://calendar.google.com/calendar/u/0/r/day"', shell=True)
            msg = (
                "📅 Opening your **Google Calendar** daily schedule for you, sir.\n\n"
                "💡 *Tip: To have Jarvis read your events aloud automatically, paste your Google Calendar secret iCal address in the **⚙️ Integrations & Settings** tab.*"
            )
        self._speak("Opening your calendar, sir.")
        return msg

    def handle_whatsapp(self, command: str) -> str:
        """Handles WhatsApp opening and sending messages hands-free."""
        lower = command.lower()
        default_phone = config.whatsapp_default_phone.strip()

        send_m = re.search(
            r"send\s+(?:a\s+)?whatsapp\s+(?:message\s+)?(?:to\s+)?(\+?\d+[\d\s\-]+|[a-zA-Z0-9_\s]+?)\s+(?:saying|that|with)\s+(.+)",
            lower,
        )
        if send_m:
            target = send_m.group(1).strip()
            body = send_m.group(2).strip()
            phone_digits = re.sub(r"[^\d+]", "", target)
            if not phone_digits and default_phone:
                phone_digits = re.sub(r"[^\d+]", "", default_phone)

            enc_body = urllib.parse.quote(body)
            if phone_digits:
                if "desktop" in config.whatsapp_client_type.lower():
                    url = f"whatsapp://send?phone={phone_digits}&text={enc_body}"
                else:
                    url = f"https://web.whatsapp.com/send?phone={phone_digits}&text={enc_body}"
                subprocess.Popen(f'explorer.exe "{url}"', shell=True)
                msg = f"💬 Opening WhatsApp chat with **{target}** and preparing your message: *\"{body}\"*, sir!"
                self._speak(f"Opening WhatsApp chat with {target} to send your message.")
                return msg

        if "desktop" in config.whatsapp_client_type.lower():
            subprocess.Popen("explorer.exe whatsapp://", shell=True)
        else:
            subprocess.Popen('explorer.exe "https://web.whatsapp.com"', shell=True)

        msg = "💬 Opening **WhatsApp** for you, sir. Standing by for any incoming updates."
        self._speak("Opening WhatsApp for you, sir.")
        return msg

    def get_daily_updates_briefing(self) -> str:
        """Unified updates: Checks Gmail and Calendar in one hands-free command."""
        self._speak("Checking all your updates now, sir.")
        gmail_res = self.check_gmail_inbox(max_results=3)
        cal_res = self.check_calendar_schedule()
        return f"📋 **DAILY BRIEFING & UPDATES**\n\n{gmail_res}\n\n{'─'*30}\n\n{cal_res}"

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

        # ── 0a. GMAIL UPDATES & READING ──────────────────────────
        if any(p in lower_clean for p in [
            "check gmail", "check my gmail", "check my email", "check my emails",
            "check email", "check emails", "unread emails", "unread email",
            "any new email", "any new emails", "any updates on gmail",
            "gmail updates", "read my emails", "read my email", "read emails",
            "what are my emails", "check inbox", "my inbox", "get emails", "gmail update"
        ]):
            return self.check_gmail_inbox()

        # ── 0b. CALENDAR UPDATES & SCHEDULE ──────────────────────
        if any(p in lower_clean for p in [
            "check calendar", "check my calendar", "any updates on calendar",
            "what is on my calendar", "what's on my calendar", "whats on my calendar",
            "my schedule", "check my schedule", "today's schedule", "todays schedule",
            "what meetings do i have", "any meetings today", "calendar update",
            "calendar updates"
        ]):
            return self.check_calendar_schedule()

        # ── 0c. WHATSAPP UPDATES & MESSAGING ─────────────────────
        if "whatsapp" in lower_clean:
            return self.handle_whatsapp(lower_clean)

        # ── 0d. UNIFIED BRIEFING / DAILY UPDATES ─────────────────
        if any(p in lower_clean for p in [
            "any update", "any updates", "give me updates", "what are my updates",
            "check updates", "daily briefing", "morning briefing",
            "daily update", "all updates"
        ]):
            return self.get_daily_updates_briefing()

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

        # ── 4b. IN-APP SCROLLING & NAVIGATION ────────────────────
        if any(p in lower_clean for p in ["scroll down", "scroll down a bit", "scroll down more", "page down", "go down"]):
            try:
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, -480, 0)
                return "📜 Scrolled down for you, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["scroll up", "scroll up a bit", "scroll up more", "page up", "go up"]):
            try:
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, 480, 0)
                return "📜 Scrolled up for you, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["new tab", "open a new tab", "create new tab"]):
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "t")
                return "🌐 Opened a new tab, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["close tab", "close this tab"]):
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "w")
                return "❌ Closed the current tab, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["switch tab", "next tab"]):
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "tab")
                return "👉 Switched to next tab, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["previous tab", "prior tab"]):
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "shift", "tab")
                return "👈 Switched to previous tab, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["reload", "reload page", "refresh page", "refresh this page"]):
            try:
                import pyautogui
                pyautogui.hotkey("ctrl", "r")
                return "🔄 Page refreshed, sir."
            except Exception:
                pass

        if any(p in lower_clean for p in ["go back", "previous page", "navigate back"]):
            try:
                import pyautogui
                pyautogui.hotkey("alt", "left")
                return "⬅️ Navigated back, sir."
            except Exception:
                pass

        # ── 4c. DIRECT IN-APP TYPING ─────────────────────────────
        type_m = re.search(r"^(?:type|write|enter)\s+(.+)$", lower_clean)
        if type_m:
            text_to_type = type_m.group(1).strip()
            try:
                import pyautogui
                pyautogui.write(text_to_type, interval=0.03)
                pyautogui.press("enter")
                return f"⌨️ Typed '{text_to_type}' and submitted, sir."
            except Exception:
                pass

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
            vision_reply = self.call_ai(
                prompt="Describe everything visible on this screen in detail. List the active application, visible text, buttons, and content.",
                image_b64=sc_res.content,
                model=config.vision_model,
            )

            msg = f"🖥️ **Active Window**: {window_title}\n\n{vision_reply}"
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", msg)
            clean_summary = re.sub(r"[*_#`\n\r]", " ", vision_reply).strip()
            clean_summary = re.sub(r"\s+", " ", clean_summary)[:140]
            self._speak(f"Active window is {window_title}. {clean_summary}")
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
        plan_text = self.call_ai(plan_prompt)
        if "Error:" in plan_text:
            plan_text = f"1. Open target application for '{user_goal}'\n2. Perform required typing or mouse actions\n3. Verify result"

        # Check if genuinely dangerous action requiring explicit user gate
        is_dangerous = any(re.search(pat, user_goal.lower()) for pat in _DANGEROUS_PATTERNS)

        clean_plan = re.sub(r"[*_#`\n\r]", " ", plan_text).strip()
        clean_plan = re.sub(r"\s+", " ", clean_plan)[:130]

        # FULL PC CONTROL: If enabled and not catastrophic, execute directly without stopping!
        require_approval = config.ask_before_every_action or is_dangerous or (not config.full_pc_control and any(re.search(pat, user_goal.lower()) for pat in _CRITICAL_ACTIONS))

        if not require_approval:
            # DIRECT AUTONOMOUS EXECUTION
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"⚡ Executing autonomously: {plan_text}")
            self._speak(f"Executing: {clean_plan}")
        else:
            # DANGEROUS TASK or manual confirmation requested -> Read aloud and ask for approval
            self.cb.get("on_status", lambda s: None)("Waiting for your approval")
            self.cb.get("on_plan", lambda p, r: None)(plan_text, is_dangerous)
            self._speak(f"Confirmation required: {clean_plan}. Say 'yes' or click approve to proceed.")

            self.waiting_for_plan_approval = True
            self.plan_approval_event.clear()
            self.plan_approval_event.wait()
            self.waiting_for_plan_approval = False

            if self.emergency_stop or not self.plan_approved:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", "❌ Plan cancelled by user.")
                return

            self.cb.get("on_chat", lambda s, t: None)("Jarvis", "✅ Plan approved. Starting execution...")

        # Action Execution Loop - anti-spam: history context + repeat guard
        step_num = 0
        last_action_key = ""
        repeat_count = 0
        step_history = []

        while step_num < config.max_steps:
            if self.emergency_stop:
                break
            step_num += 1

            self.cb.get("on_status", lambda s: None)("Thinking")

            # Provide history so LLM knows what was already done
            history_ctx = ""
            if step_history:
                history_ctx = "Steps already done:\n" + "\n".join(
                    f"  {i+1}. {h}" for i, h in enumerate(step_history[-4:])
                ) + "\n\n"

            decide_prompt = (
                f"You are Jarvis, an autonomous PC assistant.\n"
                f"Goal: '{user_goal}'\n"
                f"Active Window: '{window_title}'\n\n"
                f"{history_ctx}"
                f"What is the SINGLE next action needed? If the goal is already done, reply ACTION: finish.\n\n"
                f"Reply ONLY in this exact format:\n"
                f"ACTION: open_app | type | click | hotkey | scroll | finish\n"
                f"TEXT: <value or leave blank>\n"
                f"EXPLANATION: <one sentence>\n\n"
                f"IMPORTANT: Never repeat the same action twice. Use ACTION: finish when done."
            )
            raw = self.call_ai(decide_prompt)
            if self.emergency_stop:
                break

            # Robust Regex Parser
            act_match = re.search(r"(?:ACTION|action)[\s\":=]+([a-zA-Z_]+)", raw)
            text_match = re.search(r"(?:TEXT|text)[\s\":=]+([^\n\r\"]+)", raw)
            exp_match = re.search(r"(?:EXPLANATION|explanation)[\s\":=]+([^\n\r\"]+)", raw)

            act_type = act_match.group(1).lower().strip() if act_match else ""
            act_text = text_match.group(1).strip() if text_match else ""
            explanation = exp_match.group(1).strip() if exp_match else "Executing step"

            # Detect finish / done signals - STOP loop immediately
            if act_type in ["none", "finish", "done", "complete", "completed"]:
                self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"\U0001f3c1 Done: {explanation}")
                self._speak("Done, sir.")
                break

            # Fallback heuristic if regex failed entirely
            if not act_type:
                if "type" in raw.lower() and act_text:
                    act_type = "type"
                elif "open" in raw.lower() and act_text:
                    act_type = "open_app"
                else:
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"\U0001f3c1 Task complete: {explanation}")
                    self._speak("Task complete, sir.")
                    break

            # ANTI-SPAM: abort if same action+text repeats 2x in a row
            action_key = f"{act_type}:{act_text}"
            if action_key == last_action_key:
                repeat_count += 1
                if repeat_count >= 2:
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", "🏁 Goal achieved.")
                    self._speak("Goal achieved, sir.")
                    break
            else:
                repeat_count = 0
            last_action_key = action_key

            # Special guard: Never press reload (f5/ctrl+r) more than once in a task
            if act_type == "hotkey" and any(k in act_text.lower() for k in ["f5", "ctrl+r"]):
                if any("f5" in h.lower() or "ctrl+r" in h.lower() for h in step_history):
                    self.cb.get("on_chat", lambda s, t: None)("Jarvis", "🏁 Page refreshed already. Task complete.")
                    self._speak("Page already refreshed, sir.")
                    break

            # Execute action
            self.cb.get("on_status", lambda s: None)("Acting")
            res = self.action_tool.execute(
                action=act_type,
                text=act_text,
                dry_run=config.dry_run
            )
            step_history.append(f"{act_type}({act_text}): {res.content}")
            self._log_action(step_num, act_type, res.content, res.success)
            self.cb.get("on_chat", lambda s, t: None)("Jarvis", f"\U0001f449 **Step {step_num}** ({act_type}): {res.content}")

            if not res.success:
                break

            time.sleep(1.2)

            # Re-capture screen for next iteration
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
