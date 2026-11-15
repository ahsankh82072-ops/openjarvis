"""
Screen Assistant — Autonomous PC Screen-Seeing and Control Agent for OpenJarvis.

Usage:
    python screen_assistant.py                  # interactive text mode
    python screen_assistant.py --voice          # push-to-talk voice mode
    python screen_assistant.py --dry-run        # simulated actions only (no physical clicks)
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

# Ensure src is on Python module path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import openjarvis.tools  # registers all tools
from openjarvis.tools.computer_action import ComputerActionTool, reset_step_counter
from openjarvis.tools.describe_screen import DescribeScreenTool
from openjarvis.tools.screen_capture import ScreenCaptureTool

# Global emergency stop and exit flags
_EMERGENCY_STOP = False
_EXIT_APP = False
_LOG_FILE = os.path.join(_REPO_ROOT, "computer_actions.log")
_OLLAMA_HOST = "http://localhost:11434"
_PLANNING_MODEL = "phi3:mini"
_MAX_STEPS = 15

# Sensitive task keywords that require explicit user re-confirmation
_CRITICAL_ACTIONS = [
    "send message", "send email", "email", "delete file", "delete folder",
    "remove", "rm", "purchase", "buy", "pay", "payment", "order",
    "close unsaved", "shutdown", "reboot", "restart", "format", "settings"
]


def _log(msg: str) -> None:
    """Append a message to the persistent computer_actions.log."""
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _speak(text: str) -> None:
    """Speak text aloud using Windows TTS in a background thread."""
    def _run_tts():
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 185)
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass

    t = threading.Thread(target=_run_tts, daemon=True)
    t.start()


def _listen_mic() -> str:
    """Record speech from microphone using speech_recognition."""
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        r.energy_threshold = 300
        r.dynamic_energy_threshold = False
        r.pause_threshold = 0.8
        with sr.Microphone() as source:
            print("\n🎙️ Listening... (speak now)")
            audio = r.listen(source, timeout=10, phrase_time_limit=15)
            print("⏳ Transcribing...")
            text = r.recognize_google(audio)
            print(f"You (voice)> {text}")
            return text.strip()
    except Exception as e:
        print(f"⚠️ Mic error: {e}")
        return ""


def _emergency_listener() -> None:
    """Global hotkey listener: Ctrl+Alt+Q triggers immediate emergency stop."""
    global _EMERGENCY_STOP
    user32 = ctypes.windll.user32
    while not _EXIT_APP:
        try:
            ctrl = (user32.GetAsyncKeyState(0x11) & 0x8000) != 0
            alt = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0
            q_key = (user32.GetAsyncKeyState(0x51) & 0x8000) != 0
            if ctrl and alt and q_key:
                _EMERGENCY_STOP = True
                print("\n🚨 [EMERGENCY STOP TRIGGERED VIA CTRL+ALT+Q] All actions halted immediately!")
                _log("EMERGENCY STOP TRIGGERED VIA CTRL+ALT+Q")
                _speak("Emergency stop activated. All actions halted.")
                time.sleep(1.0)
        except Exception:
            pass
        time.sleep(0.05)


def _call_ollama(prompt: str, model: str = _PLANNING_MODEL) -> str:
    """Send a prompt to Ollama and return the text response."""
    url = f"{_OLLAMA_HOST}/api/generate"
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()
    except Exception as e:
        return f"Error contacting Ollama ({model}): {e}"


def run_task(user_goal: str, dry_run: bool = False) -> None:
    """Execute a task loop: see screen -> decide ONE step -> act -> verify -> repeat (max 15 steps)."""
    global _EMERGENCY_STOP
    if _EMERGENCY_STOP:
        print("🚨 Emergency stop is active. Restart the application or run reset_steps.")
        return

    reset_step_counter()
    screen_tool = DescribeScreenTool()
    action_tool = ComputerActionTool()

    print(f"\n🎯 Task Goal: {user_goal}")
    _log(f"NEW TASK: {user_goal} (dry_run={dry_run})")

    # Safety check: does the goal involve critical operations?
    goal_lower = user_goal.lower()
    for crit in _CRITICAL_ACTIONS:
        if crit in goal_lower:
            print(f"\n⚠️ SENSITIVE ACTION DETECTED: This task involves '{crit}'.")
            _speak(f"This task involves {crit}. Do you want me to proceed?")
            confirm = input(f"Are you sure you want Jarvis to proceed with '{crit}'? (yes/no): ").strip().lower()
            if confirm not in ["yes", "y"]:
                print("❌ Task cancelled by user.")
                _log("Task cancelled by user during critical confirmation.")
                return

    # Step 1: Look at the screen initially
    print("\n👀 Looking at your screen...")
    desc_result = screen_tool.execute(question="Summarise what is currently open on this screen.")
    screen_summary = desc_result.content if desc_result.success else "Could not capture screen."
    print(f"🖥️ Screen state:\n{screen_summary}\n")

    # Step 2: Formulate initial plan
    plan_prompt = (
        f"You are Jarvis, an autonomous computer assistant.\n"
        f"The user wants: '{user_goal}'\n"
        f"The current screen is:\n{screen_summary}\n\n"
        f"Provide a short 2 to 4 step plan to achieve this goal on Windows."
    )
    print("🧠 Formulating plan...")
    plan = _call_ollama(plan_prompt)
    print(f"\n📋 PROPOSED PLAN:\n{plan}\n")
    _speak("I have a plan, sir. Should I proceed?")

    # REQUIRE USER YES BEFORE FIRST ACTION
    user_ok = input("Proceed with this plan? (yes/no): ").strip().lower()
    if user_ok not in ["yes", "y"]:
        print("❌ Plan not approved. Task aborted.")
        _log("Plan rejected by user.")
        return

    # Step 3: Execution loop (up to 15 steps)
    step_num = 0
    while step_num < _MAX_STEPS:
        step_num += 1
        if _EMERGENCY_STOP:
            print("\n🚨 Emergency stop halted the execution loop!")
            break

        print(f"\n--- STEP {step_num} of {_MAX_STEPS} ---")

        # Decide ONE action using model
        decide_prompt = (
            f"You are an assistant controlling a Windows PC.\n"
            f"Goal: '{user_goal}'\n"
            f"Current screen description:\n{screen_summary}\n\n"
            f"Decide the NEXT SINGLE action.\n"
            f"Answer ONLY in this JSON format:\n"
            f'{{"action": "open_app"|"hotkey"|"type"|"click"|"scroll"|"finish", "text": "...", "keys": ["ctrl", "..."], "x": 0, "y": 0, "explanation": "..."}}'
        )
        decision_raw = _call_ollama(decide_prompt)
        _log(f"Step {step_num} raw decision: {decision_raw}")

        # Parse JSON
        parsed_action: dict = {}
        try:
            match = re.search(r"\{.*\}", decision_raw, re.DOTALL)
            if match:
                parsed_action = json.loads(match.group(0))
        except Exception:
            pass

        act_type = parsed_action.get("action", "")
        explanation = parsed_action.get("explanation", decision_raw[:100])

        if not act_type or act_type == "finish":
            print(f"🏁 Task complete or no further action needed: {explanation}")
            _speak("Task completed, sir.")
            _log(f"Task finished at step {step_num}")
            break

        print(f"👉 Action: {act_type} | Reason: {explanation}")

        # Execute action with safety tool
        parsed_action["dry_run"] = dry_run
        act_res = action_tool.execute(**parsed_action)
        print(f"Result: {act_res.content}")
        _log(f"Step {step_num} execution result: {act_res.content}")

        if not act_res.success:
            print(f"⚠️ Action failed or blocked: {act_res.content}")
            if act_res.metadata.get("security_block") or act_res.metadata.get("failsafe"):
                print("🛑 Safety stop triggered.")
                break

        time.sleep(1.0)

        # Look again to verify
        print("👀 Checking screen changes...")
        desc_result = screen_tool.execute(question="Did the last action work as expected? Describe the active window.")
        screen_summary = desc_result.content if desc_result.success else "Could not re-capture screen."

    if step_num >= _MAX_STEPS:
        print(f"\n⚠️ Reached maximum {_MAX_STEPS} steps ceiling. Stopping.")
        _speak("Reached maximum 15 steps. Pausing for instructions.")


def main():
    global _EXIT_APP
    parser = argparse.ArgumentParser(description="OpenJarvis Screen Assistant")
    parser.add_argument("--voice", action="store_true", help="Enable push-to-talk voice input")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without mouse/keyboard movement")
    args = parser.parse_args()

    # Start emergency stop hotkey listener thread (Ctrl+Alt+Q)
    t = threading.Thread(target=_emergency_listener, daemon=True)
    t.start()

    print("=" * 65)
    print("   🤖 OPENJARVIS SCREEN ASSISTANT (Windows 10)")
    print("=" * 65)
    print("• Seeing Screen : mss + Ollama moondream (local)")
    print("• Action Safety : PyAutoGUI + 15-step ceiling + password blockers")
    print("• Emergency Stop: Press Ctrl + Alt + Q at any time!")
    print("• Corner Stop   : Move mouse quickly to upper-left screen corner")
    if args.dry_run:
        print("• Mode          : 🟡 DRY RUN (simulated actions only)")
    if args.voice:
        print("• Voice Input   : 🎙️ ACTIVE (press Enter to speak)")
    print("=" * 65)

    _speak("Screen Assistant is online and ready, sir.")

    try:
        while not _EXIT_APP:
            if args.voice:
                input("\nPress [Enter] to speak (or Ctrl+C to exit)... ")
                goal = _listen_mic()
            else:
                goal = input("\nEnter task (e.g. 'what is on my screen', 'open notepad') or 'exit': ").strip()

            if not goal:
                continue
            if goal.lower() in ["exit", "quit", "q"]:
                break
            if goal.lower() in ["what is on my screen", "what's on my screen", "describe screen", "summarise this page"]:
                print("\n👀 Analyzing screen...")
                res = DescribeScreenTool().execute()
                print(f"\n{res.content}\n")
                _speak("Here is what I see on your screen.")
                continue

            run_task(goal, dry_run=args.dry_run)

    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        _EXIT_APP = True
        print("\n👋 Screen Assistant stopped. Goodbye!")


if __name__ == "__main__":
    main()
