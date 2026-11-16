"""
gemini_live_engine.py — High-Performance Bidirectional Gemini Live API Engine.

Features:
  1. Real-time bidirectional streaming over WebSockets via google-genai SDK.
  2. Microphone streaming (16kHz PCM mono) via sounddevice.
  3. Audio playback (24kHz PCM mono) with instant interruption support.
  4. Real-time screen sharing (~1 fps, resized JPEG) with automatic sensitive page detection.
  5. Function calling with full OpenJarvis safety layer:
     - describe_screen, click, double_click, type_text, hotkey, scroll, open_app, take_note
     - 15-step ceiling, password/OTP blocking, critical action confirmation gate.
  6. Global emergency stop (Ctrl+Alt+Q) and Push-to-Talk (Ctrl+Space).
  7. Robust reconnection logic on session timeout or transient network drops.
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import sounddevice as sd
from PIL import Image

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from config import config
from openjarvis.tools.computer_action import ComputerActionTool, reset_step_counter
from openjarvis.tools.screen_capture import ScreenCaptureTool

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

# Audio constraints
_MIC_SAMPLE_RATE = 16000
_PLAYBACK_SAMPLE_RATE = 24000
_CHANNELS = 1

# Sensitive keywords that pause screen share immediately
_SENSITIVE_WINDOW_KEYWORDS = [
    "sign in", "login", "checkout", "payment", "bank", "credit card",
    "password", "otp", "2fa", "billing", "authenticate"
]

# Critical actions requiring explicit confirmation
_CRITICAL_ACTIONS = [
    r"\bdelete\b", r"\bformat\b", r"\bshutdown\b", r"\breboot\b",
    r"\bpurchase\b", r"\bbuy\b", r"\bpayment\b", r"\bsend\s+message\b",
    r"\bclose\s+unsaved\b", r"\bmodify\s+system\b", r"\brmdir\b"
]


class GeminiLiveEngine:
    """Manages an active real-time Gemini Live WebSocket session with voice and vision."""

    def __init__(self, callbacks: Optional[Dict[str, Callable[..., Any]]] = None) -> None:
        self.callbacks = callbacks or {}
        self.is_running = False
        self.is_connected = False
        self.screen_share_active = False
        self.ptt_active = False
        self.is_speaking = False
        self.emergency_stop = False
        self._reconnect_attempts = 0

        # Safety & action tools
        self.action_tool = ComputerActionTool()
        self.screen_tool = ScreenCaptureTool()

        # Confirmation event for critical actions
        self._confirm_event = threading.Event()
        self._confirm_decision = False
        self.waiting_for_confirmation = False

        # Audio Queues & Streams
        self._mic_queue: Optional[asyncio.Queue] = None
        self._playback_queue: queue.Queue = queue.Queue()
        self._playback_thread: Optional[threading.Thread] = None
        self._stop_playback = threading.Event()

        # Background thread and loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._engine_thread: Optional[threading.Thread] = None
        self._session_task: Optional[asyncio.Task] = None
        self._current_session = None

        # Hotkey listener thread
        self._hotkey_thread: Optional[threading.Thread] = None
        self._exit_hotkeys = False

    # ─────────────────────────────────────────────────────────────
    #  PUBLIC CONTROL METHODS
    # ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Launch the Gemini Live background engine."""
        if self.is_running:
            return
        if genai is None or types is None:
            self._notify_error("google-genai package is not installed. Please run: pip install google-genai sounddevice")
            return

        self.emergency_stop = False
        self.is_running = True
        self._reconnect_attempts = 0
        reset_step_counter()

        # Start hotkey listener (Ctrl+Space for PTT, Ctrl+Alt+Q for emergency stop)
        self._exit_hotkeys = False
        self._hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        self._hotkey_thread.start()

        # Start playback worker thread
        self._stop_playback.clear()
        self._playback_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._playback_thread.start()

        # Start async engine thread
        self._engine_thread = threading.Thread(target=self._run_async_engine, daemon=True)
        self._engine_thread.start()

    def stop(self) -> None:
        """Stop the Gemini Live session, microphone, and all execution."""
        self.emergency_stop = True
        self.is_running = False
        self.is_connected = False
        self.screen_share_active = False
        self._exit_hotkeys = True

        self._flush_playback()
        self._stop_playback.set()

        # Stop async tasks
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._cancel_active_tasks)

        self._notify_status("Stopped")
        self._notify_screen_share(False)

    def set_screen_share(self, active: bool) -> None:
        """Toggle real-time screen sharing on or off."""
        if not self.is_running:
            return
        self.screen_share_active = active
        self._notify_screen_share(active)
        if active:
            self._notify_chat("Jarvis", "🖥️ Screen sharing activated. I can now see what is on your screen.")
        else:
            self._notify_chat("Jarvis", "🖥️ Screen sharing stopped.")

    def set_ptt(self, pressed: bool) -> None:
        """Set push-to-talk button/key state."""
        self.ptt_active = pressed
        if pressed:
            # User wants to speak -> interrupt any ongoing playback
            self._flush_playback()
            self._notify_status("Listening")
        else:
            self._notify_status("Thinking")
            # Signal end of user audio stream turn so Gemini generates reply
            if self._current_session and self._loop and self._loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._current_session.send_realtime_input(audio_stream_end=True),
                        self._loop
                    )
                except Exception:
                    pass

    def approve_action(self, approved: bool) -> None:
        """Callback from UI when user confirms or rejects a critical action."""
        self._confirm_decision = approved
        self._confirm_event.set()

    # ─────────────────────────────────────────────────────────────
    #  AUDIO PLAYBACK WORKER (SPEAKER)
    # ─────────────────────────────────────────────────────────────
    def _playback_worker(self) -> None:
        """Plays 24kHz PCM audio chunks streamed back by Gemini Live."""
        try:
            out_stream = sd.RawOutputStream(
                samplerate=_PLAYBACK_SAMPLE_RATE,
                channels=_CHANNELS,
                dtype="int16",
                blocksize=1024,
            )
            out_stream.start()
        except Exception as e:
            self._notify_error(f"Failed to open speaker audio stream: {e}")
            return

        try:
            while not self._stop_playback.is_set():
                try:
                    chunk = self._playback_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if self._stop_playback.is_set() or self.emergency_stop:
                    break

                if chunk:
                    try:
                        self.is_speaking = True
                        self._notify_status("Speaking")
                        out_stream.write(chunk)
                    except Exception:
                        pass
                else:
                    self.is_speaking = False
        finally:
            try:
                out_stream.stop()
                out_stream.close()
            except Exception:
                pass
            self.is_speaking = False

    def _flush_playback(self) -> None:
        """Instantly flush all queued audio to support natural user interruption."""
        while not self._playback_queue.empty():
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                break
        self.is_speaking = False

    # ─────────────────────────────────────────────────────────────
    #  ASYNC MAIN RUNNER
    # ─────────────────────────────────────────────────────────────
    def _run_async_engine(self) -> None:
        """Runs the asyncio event loop for the live session."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._live_session_supervisor())
        finally:
            self._loop.close()

    def _cancel_active_tasks(self) -> None:
        if self._session_task and not self._session_task.done():
            self._session_task.cancel()

    async def _live_session_supervisor(self) -> None:
        """Supervises session connectivity and reconnects once on unexpected disconnect."""
        while self.is_running and not self.emergency_stop:
            try:
                await self._run_single_session()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                err_str = str(exc)
                if "API_KEY" in err_str.upper() or "INVALID" in err_str.upper():
                    self._notify_error(f"Authentication error: {exc}. Please verify GEMINI_API_KEY.")
                    break
                elif "RATE" in err_str.upper() or "QUOTA" in err_str.upper():
                    self._notify_error("Gemini Live quota limit reached. Please wait a moment.")
                    break
                else:
                    # Attempt 1 graceful reconnection on timeout or socket drop
                    if self._reconnect_attempts < 1 and self.is_running:
                        self._reconnect_attempts += 1
                        self._notify_chat("Jarvis", "🔄 Live session timed out or disconnected. Reconnecting...")
                        await asyncio.sleep(1.5)
                        continue
                    else:
                        self._notify_error(f"Live session closed: {exc}")
                        break
        self.is_running = False
        self.is_connected = False
        self._notify_status("Idle")

    # ─────────────────────────────────────────────────────────────
    #  CORE LIVE SESSION LOGIC
    # ─────────────────────────────────────────────────────────────
    async def _run_single_session(self) -> None:
        """Initializes client, sets up tools, and runs bidirectional streaming."""
        # 1. API Key resolution (Never printed or saved in files)
        api_key = (os.environ.get("GEMINI_API_KEY") or config.gemini_api_key or "").strip()
        if not api_key:
            self._notify_error("GEMINI_API_KEY environment variable is not set. Please set it or enter it in Settings.")
            self.is_running = False
            return

        client = genai.Client(api_key=api_key, http_options={"api_version": "v1beta"})
        model_id = (config.gemini_live_model or "gemini-2.5-flash-native-audio-latest").strip()
        if "live-001" in model_id:
            model_id = "gemini-2.5-flash-native-audio-latest"
        voice_name = config.live_voice or "Puck"

        # 2. Tools Declaration
        tools_list = self._build_tool_declarations()

        # 3. Live Configuration
        system_prompt = (
            "You are Jarvis, a friendly, quick voice assistant. Keep answers short and natural. "
            "When a task needs the computer, say what you are about to do, then do it with your tools. "
            "If you are unsure where to click, ask me."
        )

        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=system_prompt)]
            ),
            tools=tools_list,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        self._notify_status("Connecting")
        self._mic_queue = asyncio.Queue()

        # Open microphone input stream
        mic_stream = None
        try:
            def _mic_callback(indata, frames, time_info, status):
                if status and "overflow" not in str(status).lower():
                    pass
                if self.is_running and not self.emergency_stop:
                    # If PTT is enabled, stream audio; else stream continuously
                    raw = bytes(indata)
                    if self._loop and self._mic_queue:
                        self._loop.call_soon_threadsafe(self._mic_queue.put_nowait, raw)

            mic_stream = sd.RawInputStream(
                samplerate=_MIC_SAMPLE_RATE,
                channels=_CHANNELS,
                dtype="int16",
                blocksize=1024,
                callback=_mic_callback,
            )
            mic_stream.start()
        except Exception as e:
            self._notify_error(f"Could not initialize microphone: {e}")
            return

        try:
            async with client.aio.live.connect(model=model_id, config=live_config) as session:
                self._current_session = session
                self.is_connected = True
                self._reconnect_attempts = 0
                self._notify_status("Live")
                self._notify_chat("Jarvis", f"⚡ Connected to Gemini Live ({model_id}, Voice: {voice_name}). Standing by...")

                # Launch concurrent coroutines
                mic_task = asyncio.create_task(self._mic_sender_loop(session))
                screen_task = asyncio.create_task(self._screen_sender_loop(session))
                receive_task = asyncio.create_task(self._receive_loop(session))

                # Wait until any task errors or session closes
                done, pending = await asyncio.wait(
                    [mic_task, screen_task, receive_task],
                    return_when=asyncio.FIRST_EXCEPTION
                )

                for t in pending:
                    t.cancel()

                for t in done:
                    if t.exception():
                        raise t.exception()
        finally:
            if mic_stream:
                try:
                    mic_stream.stop()
                    mic_stream.close()
                except Exception:
                    pass
            self._current_session = None
            self.is_connected = False

    # ─────────────────────────────────────────────────────────────
    #  MIC SENDER LOOP
    # ─────────────────────────────────────────────────────────────
    async def _mic_sender_loop(self, session: Any) -> None:
        """Pulls audio bytes from microphone queue and streams to Gemini Live."""
        while self.is_running and not self.emergency_stop:
            pcm_chunk = await self._mic_queue.get()
            if self.emergency_stop:
                break

            # If user spoke, trigger visualizer pulse
            if not self.is_speaking and not self.ptt_active:
                self._notify_status("Listening")

            try:
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_chunk,
                        mime_type=f"audio/pcm;rate={_MIC_SAMPLE_RATE}"
                    )
                )
            except Exception as e:
                break

    # ─────────────────────────────────────────────────────────────
    #  SCREEN SENDER LOOP (~1 FPS WITH SENSITIVE SCREEN GUARD)
    # ─────────────────────────────────────────────────────────────
    async def _screen_sender_loop(self, session: Any) -> None:
        """Streams desktop screenshots when screen sharing is enabled."""
        while self.is_running and not self.emergency_stop:
            await asyncio.sleep(1.0)
            if not self.screen_share_active or self.emergency_stop:
                continue

            # 1. Inspect foreground window for sensitive login/payment content
            active_title = self._get_active_window_title().lower()
            is_sensitive = any(kw in active_title for kw in _SENSITIVE_WINDOW_KEYWORDS)

            if is_sensitive:
                # INSTANT SAFETY CUTOFF: Auto-stop screen sharing and alert user
                self.screen_share_active = False
                self._notify_screen_share(False)
                alert_msg = f"⚠️ Sensitive window detected ('{active_title}'). Screen share auto-paused for security."
                self._notify_chat("Jarvis", alert_msg)
                continue

            # 2. Capture and resize screenshot to keep bandwidth minimal (~40-60KB JPEG)
            try:
                sc_res = self.screen_tool.execute(resize=True)
                if sc_res.success and sc_res.content:
                    raw_png = base64.b64decode(sc_res.content)
                    # Convert PNG to high-efficiency JPEG
                    img = Image.open(io.BytesIO(raw_png)).convert("RGB")
                    img.thumbnail((1024, 576), Image.LANCZOS)
                    jpeg_buf = io.BytesIO()
                    img.save(jpeg_buf, format="JPEG", quality=68)
                    jpeg_bytes = jpeg_buf.getvalue()

                    await session.send_realtime_input(
                        media=types.Blob(
                            data=jpeg_bytes,
                            mime_type="image/jpeg"
                        )
                    )
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    #  RECEIVE LOOP (AUDIO, TRANSCRIPTS & FUNCTION CALLS)
    # ─────────────────────────────────────────────────────────────
    async def _receive_loop(self, session: Any) -> None:
        """Receives live model responses, audio streams, and tool requests."""
        async for response in session.receive():
            if self.emergency_stop:
                break

            server_content = response.server_content
            if server_content is not None:
                # 1. Handle user interruption signal
                if server_content.interrupted:
                    self._flush_playback()
                    self._notify_status("Listening")

                # 2. Real-time text transcript for user input
                if server_content.input_transcription and server_content.input_transcription.text:
                    u_text = server_content.input_transcription.text.strip()
                    if u_text:
                        self._notify_transcript("You", u_text, is_final=False)

                # 3. Model turn audio parts & output transcription
                if server_content.model_turn:
                    for part in server_content.model_turn.parts:
                        # Output audio chunk
                        if part.inline_data and part.inline_data.data:
                            self._playback_queue.put(part.inline_data.data)

                        # Output text chunk
                        if part.text:
                            self._notify_transcript("Jarvis", part.text, is_final=False)

                if server_content.output_transcription and server_content.output_transcription.text:
                    j_text = server_content.output_transcription.text.strip()
                    if j_text:
                        self._notify_transcript("Jarvis", j_text, is_final=True)

                if server_content.turn_complete:
                    self._notify_status("Idle")

            # 4. Handle Tool / Function Calling
            tool_call = response.tool_call
            if tool_call:
                self._notify_status("Acting")
                for fn_call in tool_call.function_calls:
                    name = fn_call.name
                    args = fn_call.args or {}
                    call_id = fn_call.id

                    # Execute tool through safety gate
                    tool_result_str = await self._execute_safe_tool(name, args)

                    # Send tool response back to Gemini session
                    try:
                        await session.send_tool_response(
                            function_responses=[
                                types.FunctionResponse(
                                    name=name,
                                    id=call_id,
                                    response={"result": tool_result_str}
                                )
                            ]
                        )
                    except Exception as e:
                        pass

    # ─────────────────────────────────────────────────────────────
    #  TOOL EXECUTION WITH SAFETY GUARDS & CONFIRMATION
    # ─────────────────────────────────────────────────────────────
    async def _execute_safe_tool(self, name: str, args: Dict[str, Any]) -> str:
        """Executes a requested tool function while applying all safety checks."""
        # 1. Safety Check: Critical actions requiring user confirmation
        desc_str = f"{name}({args})"
        is_critical = any(re.search(pat, desc_str.lower()) for pat in _CRITICAL_ACTIONS)

        if is_critical or config.ask_before_every_action:
            # Request user approval via callback
            self.waiting_for_confirmation = True
            self._confirm_event.clear()
            self._notify_status("Waiting for your approval")
            confirm_prompt = f"Confirm: Jarvis wants to execute '{desc_str}'. Approve?"
            self._notify_confirm(confirm_prompt)

            # Wait for user decision (UI button or voice)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._confirm_event.wait)
            self.waiting_for_confirmation = False

            if not self._confirm_decision or self.emergency_stop:
                self._notify_chat("Jarvis", f"❌ Action cancelled: '{desc_str}'.")
                return "Action cancelled by user for safety."

        # 2. Dispatch to specific tool implementation
        try:
            if name == "describe_screen":
                q = str(args.get("question", "What is currently on the screen?"))
                sc_res = self.screen_tool.execute(resize=True)
                win = sc_res.metadata.get("active_window", "Desktop")
                self._notify_chat("Jarvis", f"👀 Inspecting screen for: '{q}' (Active: {win})")
                return f"Active Window: {win}. Screenshot captured for analysis."

            elif name == "click":
                x = args.get("x", -1)
                y = args.get("y", -1)
                res = self.action_tool.execute(action="click", x=None if x < 0 else x, y=None if y < 0 else y)
                self._log_and_notify_action("click", f"at ({x}, {y})", res.content)
                return res.content

            elif name == "double_click":
                x = args.get("x", -1)
                y = args.get("y", -1)
                res = self.action_tool.execute(action="double_click", x=None if x < 0 else x, y=None if y < 0 else y)
                self._log_and_notify_action("double_click", f"at ({x}, {y})", res.content)
                return res.content

            elif name == "type_text":
                text = str(args.get("text", ""))
                res = self.action_tool.execute(action="type", text=text)
                self._log_and_notify_action("type", text, res.content)
                return res.content

            elif name == "hotkey":
                keys_val = args.get("keys", "")
                keys_list = [k.strip() for k in str(keys_val).split("+") if k.strip()]
                res = self.action_tool.execute(action="hotkey", keys=keys_list)
                self._log_and_notify_action("hotkey", keys_val, res.content)
                return res.content

            elif name == "scroll":
                clicks = int(args.get("clicks", 0))
                res = self.action_tool.execute(action="scroll", clicks=clicks)
                self._log_and_notify_action("scroll", f"{clicks} units", res.content)
                return res.content

            elif name == "open_app":
                app_cmd = str(args.get("app_name", ""))
                res = self.action_tool.execute(action="open_app", text=app_cmd)
                self._log_and_notify_action("open_app", app_cmd, res.content)
                return res.content

            elif name == "take_note":
                note_text = str(args.get("note", "")).strip()
                notes_file = os.path.expanduser("~/.openjarvis/notes.txt")
                os.makedirs(os.path.dirname(notes_file), exist_ok=True)
                ts = datetime_now = time.strftime("%Y-%m-%d %H:%M:%S")
                with open(notes_file, "a", encoding="utf-8") as f:
                    f.write(f"\n[{ts}] {note_text}\n")
                subprocess.Popen(f'notepad.exe "{notes_file}"', shell=True)
                msg = f"Saved note to {notes_file} and opened in Notepad."
                self._log_and_notify_action("take_note", note_text, msg)
                return msg

            else:
                return f"Error: Tool '{name}' is not recognized."
        except Exception as ex:
            return f"Tool execution failed: {ex}"

    def _log_and_notify_action(self, action: str, details: Any, result: str) -> None:
        """Appends action to audit trail callback and chat."""
        log_entry = f"[Gemini Live] ACTION: {action} ({details}) -> {result}"
        self.callbacks.get("on_log", lambda l: None)(log_entry)
        self._notify_chat("Jarvis", f"👉 **Action**: `{action}` ({details})")

    # ─────────────────────────────────────────────────────────────
    #  TOOL DECLARATIONS FOR GEMINI LIVE
    # ─────────────────────────────────────────────────────────────
    def _build_tool_declarations(self) -> List[Any]:
        """Constructs schema definitions for all tools exposed to Gemini Live."""
        declarations = [
            types.FunctionDeclaration(
                name="describe_screen",
                description="Inspect the user's active screen and window to see what is currently visible.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Specific question about what is on screen."}
                    }
                }
            ),
            types.FunctionDeclaration(
                name="click",
                description="Click at screen coordinates (x, y) or at current cursor position if omitted.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate in screen pixels."},
                        "y": {"type": "integer", "description": "Y coordinate in screen pixels."}
                    }
                }
            ),
            types.FunctionDeclaration(
                name="double_click",
                description="Double-click at screen coordinates (x, y) or at current cursor position.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "X coordinate in screen pixels."},
                        "y": {"type": "integer", "description": "Y coordinate in screen pixels."}
                    }
                }
            ),
            types.FunctionDeclaration(
                name="type_text",
                description="Type text into the focused active window or input field.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The exact text characters to type."}
                    },
                    "required": ["text"]
                }
            ),
            types.FunctionDeclaration(
                name="hotkey",
                description="Press a keyboard shortcut like 'ctrl+c', 'ctrl+v', 'alt+tab', 'enter', 'win'.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "keys": {"type": "string", "description": "Combination of keys, e.g. 'ctrl+t', 'enter'."}
                    },
                    "required": ["keys"]
                }
            ),
            types.FunctionDeclaration(
                name="scroll",
                description="Scroll the active page. Positive value scrolls up, negative value scrolls down.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "clicks": {"type": "integer", "description": "Scroll amount, e.g. -300 for down, 300 for up."}
                    },
                    "required": ["clicks"]
                }
            ),
            types.FunctionDeclaration(
                name="open_app",
                description="Launch a desktop application, website URL, or system command.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "app_name": {"type": "string", "description": "App executable or URL, e.g. 'chrome', 'notepad', 'https://youtube.com'."}
                    },
                    "required": ["app_name"]
                }
            ),
            types.FunctionDeclaration(
                name="take_note",
                description="Quickly save a note to ~/.openjarvis/notes.txt and open it for the user.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "note": {"type": "string", "description": "The text content of the note."}
                    },
                    "required": ["note"]
                }
            ),
        ]
        return [types.Tool(function_declarations=declarations)]

    # ─────────────────────────────────────────────────────────────
    #  GLOBAL HOTKEY LISTENER (Ctrl+Space for PTT, Ctrl+Alt+Q for STOP)
    # ─────────────────────────────────────────────────────────────
    def _hotkey_listener(self) -> None:
        """Listens globally for Ctrl+Space (Push-To-Talk) and Ctrl+Alt+Q (Emergency Stop)."""
        user32 = ctypes.windll.user32
        space_was_down = False
        while not self._exit_hotkeys:
            try:
                ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
                alt = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0
                q_key = (user32.GetAsyncKeyState(0x51) & 0x8000) != 0
                space_key = (user32.GetAsyncKeyState(0x20) & 0x8000) != 0

                # Emergency Stop: Ctrl + Alt + Q
                if ctrl and alt and q_key:
                    self.stop()
                    break

                # Push-to-Talk: Ctrl + Space
                if ctrl and space_key:
                    if not space_was_down:
                        space_was_down = True
                        self.set_ptt(True)
                else:
                    if space_was_down:
                        space_was_down = False
                        self.set_ptt(False)

                time.sleep(0.04)
            except Exception:
                time.sleep(0.1)

    def _get_active_window_title(self) -> str:
        """Helper to get focused window name for safety check."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return (buf.value or "").strip()
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────
    #  CALLBACK NOTIFIERS
    # ─────────────────────────────────────────────────────────────
    def _notify_status(self, status: str) -> None:
        if getattr(self, "_last_status", None) == status:
            return
        self._last_status = status
        cb = self.callbacks.get("on_status")
        if cb:
            cb(status)

    def _notify_transcript(self, sender: str, text: str, is_final: bool = False) -> None:
        cb = self.callbacks.get("on_transcript")
        if cb:
            cb(sender, text, is_final)

    def _notify_chat(self, sender: str, text: str) -> None:
        cb = self.callbacks.get("on_chat")
        if cb:
            cb(sender, text)

    def _notify_screen_share(self, active: bool) -> None:
        cb = self.callbacks.get("on_screen_share")
        if cb:
            cb(active)

    def _notify_error(self, err: str) -> None:
        cb = self.callbacks.get("on_error")
        if cb:
            cb(err)
        self._notify_chat("Jarvis", f"⚠️ {err}")

    def _notify_confirm(self, prompt: str) -> None:
        cb = self.callbacks.get("on_confirm")
        if cb:
            cb(prompt)
