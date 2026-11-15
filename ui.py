"""
ui.py — Modern Dark Graphical Desktop Application for Jarvis Screen Assistant.
Built using CustomTkinter with real-time screen preview, plan approval cards,
action logging, settings, push-to-talk voice animations, and system tray.
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

# Import local worker and configuration
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config import config
from worker import JarvisWorker

# Appearance setup
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

_ACCENT_CYAN = "#00e5ff"
_ACCENT_RED = "#ff3366"
_ACCENT_GREEN = "#00e676"
_BG_DARK = "#0d1117"
_CARD_BG = "#161b22"
_USER_BUBBLE = "#1f3a5f"
_JARVIS_BUBBLE = "#1b2838"


class JarvisApp(ctk.CTk):
    """Main Application Window for Jarvis."""

    def __init__(self) -> None:
        super().__init__()

        self.title("J.A.R.V.I.S. — Desktop Screen Assistant")
        self.geometry("980x720")
        self.minsize(840, 600)

        # Worker initialization
        self.worker = JarvisWorker(
            callbacks={
                "on_status": self._thread_safe(self.update_status),
                "on_chat": self._thread_safe(self.add_chat_message),
                "on_plan": self._thread_safe(self.show_plan_card),
                "on_screenshot": self._thread_safe(self.update_screenshot_preview),
                "on_log": self._thread_safe(self.append_log_entry),
                "on_task_done": self._thread_safe(self.on_task_completed),
            }
        )

        # UI state
        self.is_listening = False
        self._mic_pulse_step = 0
        self._thumbnail_img: Optional[ctk.CTkImage] = None

        self._build_ui()
        self._setup_system_tray()

        # Apply saved settings
        if config.always_on_top:
            self.attributes("-topmost", True)
            self.topmost_switch.select()

        # Welcome message
        self.add_chat_message(
            "Jarvis",
            "Greetings! I am Jarvis, your autonomous screen assistant.\n"
            "• Ask **'What's on my screen?'** or click the preview button.\n"
            "• Ask me to perform computer tasks like opening apps or typing.\n"
            "• Emergency Stop: Click the red STOP button or press **Ctrl + Alt + Q**.",
        )

    def _thread_safe(self, func):
        """Wrap worker callbacks to ensure execution on Tkinter's main thread."""
        def _wrapper(*args, **kwargs):
            self.after(0, lambda: func(*args, **kwargs))
        return _wrapper

    # ─────────────────────────────────────────────────────────────
    #  UI LAYOUT
    # ─────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        # 1. Top Header Bar
        self.header_frame = ctk.CTkFrame(self, height=54, corner_radius=0, fg_color="#101620")
        self.header_frame.pack(fill="x", side="top")

        # Title Label
        self.logo_lbl = ctk.CTkLabel(
            self.header_frame,
            text="⚡ J.A.R.V.I.S.",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=_ACCENT_CYAN,
        )
        self.logo_lbl.pack(side="left", padx=16, pady=8)

        # Status Badge Frame
        self.status_container = ctk.CTkFrame(self.header_frame, fg_color="#182330", corner_radius=14)
        self.status_container.pack(side="left", padx=10, pady=8)

        self.status_dot = ctk.CTkLabel(self.status_container, text="●", text_color=_ACCENT_GREEN, font=ctk.CTkFont(size=14))
        self.status_dot.pack(side="left", padx=(10, 4), pady=4)

        self.status_lbl = ctk.CTkLabel(
            self.status_container,
            text="Idle",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color="#c9d1d9",
        )
        self.status_lbl.pack(side="left", padx=(0, 12), pady=4)

        # Big Red Emergency STOP Button
        self.stop_btn = ctk.CTkButton(
            self.header_frame,
            text="🚨 EMERGENCY STOP (Ctrl+Alt+Q)",
            fg_color="#d32f2f",
            hover_color="#b71c1c",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            command=self.on_emergency_stop_clicked,
        )
        self.stop_btn.pack(side="right", padx=14, pady=8)

        # Always-On-Top Switch
        self.topmost_switch = ctk.CTkSwitch(
            self.header_frame,
            text="Pin on top",
            font=ctk.CTkFont(size=12),
            command=self.toggle_always_on_top,
        )
        self.topmost_switch.pack(side="right", padx=12, pady=8)

        # 2. Main Content Split (Left: Tabs | Right: Screen Preview)
        self.body_paned = ctk.CTkFrame(self, fg_color=_BG_DARK)
        self.body_paned.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        # Right Sidebar for Screen Preview
        self.sidebar_frame = ctk.CTkFrame(self.body_paned, width=260, fg_color=_CARD_BG, corner_radius=10)
        self.sidebar_frame.pack(side="right", fill="y", padx=(6, 0), pady=4)
        self.sidebar_frame.pack_propagate(False)

        self._build_sidebar()

        # Left Notebook/Tabs
        self.tabview = ctk.CTkTabview(self.body_paned, fg_color="#121820", segmented_button_selected_color=_ACCENT_CYAN)
        self.tabview.pack(side="left", fill="both", expand=True, padx=(0, 4), pady=0)

        self.chat_tab = self.tabview.add("💬 Assistant Chat")
        self.logs_tab = self.tabview.add("📜 Action Log")
        self.settings_tab = self.tabview.add("⚙️ Settings")

        self._build_chat_tab()
        self._build_logs_tab()
        self._build_settings_tab()

    def _build_sidebar(self) -> None:
        """Right sidebar containing live screen thumbnail and quick trigger."""
        lbl = ctk.CTkLabel(
            self.sidebar_frame,
            text="🖥️ SCREEN PREVIEW",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_ACCENT_CYAN,
        )
        lbl.pack(anchor="w", padx=12, pady=(12, 6))

        # Preview Thumbnail Box
        self.preview_lbl = ctk.CTkLabel(
            self.sidebar_frame,
            text="No screenshot taken yet",
            width=236,
            height=140,
            fg_color="#0d1117",
            corner_radius=8,
            text_color="#8b949e",
        )
        self.preview_lbl.pack(padx=12, pady=6)

        # Active Window Label
        self.win_title_lbl = ctk.CTkLabel(
            self.sidebar_frame,
            text="Window: Active Desktop",
            font=ctk.CTkFont(size=11),
            text_color="#8b949e",
            wraplength=230,
            justify="left",
        )
        self.win_title_lbl.pack(anchor="w", padx=12, pady=(2, 10))

        # Quick Action Button: What's on my screen?
        self.inspect_btn = ctk.CTkButton(
            self.sidebar_frame,
            text="👀 What's on my screen?",
            fg_color="#006699",
            hover_color="#0088cc",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            command=self.on_inspect_screen_clicked,
        )
        self.inspect_btn.pack(fill="x", padx=12, pady=6)

        # Info Box
        info_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="#101722", corner_radius=8)
        info_frame.pack(fill="x", padx=12, pady=(16, 8))

        ctk.CTkLabel(
            info_frame,
            text="🛡️ Safety Controls Active\n• Max 15 steps per task\n• Passwords blocked\n• Corner mouse abort",
            font=ctk.CTkFont(size=11),
            text_color="#7ee787",
            justify="left",
        ).pack(padx=10, pady=8)

    def _build_chat_tab(self) -> None:
        """Chat message area, Plan Approval Card, and Input Bar."""
        # Chat Messages Scroll Area
        self.chat_scroll = ctk.CTkScrollableFrame(self.chat_tab, fg_color="transparent")
        self.chat_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # Plan Approval Card Container (Hidden by default)
        self.plan_card = ctk.CTkFrame(self.chat_tab, fg_color="#1f242c", corner_radius=10, border_width=2, border_color=_ACCENT_CYAN)

        self.plan_card_header = ctk.CTkLabel(
            self.plan_card,
            text="📋 PROPOSED PLAN",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=_ACCENT_CYAN,
        )
        self.plan_card_header.pack(anchor="w", padx=14, pady=(8, 2))

        self.plan_text_lbl = ctk.CTkLabel(
            self.plan_card,
            text="",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#f0f6fc",
            justify="left",
            wraplength=520,
        )
        self.plan_text_lbl.pack(anchor="w", padx=14, pady=4)

        self.plan_btn_frame = ctk.CTkFrame(self.plan_card, fg_color="transparent")
        self.plan_btn_frame.pack(fill="x", padx=14, pady=(6, 10))

        self.approve_btn = ctk.CTkButton(
            self.plan_btn_frame,
            text="✔ APPROVE & EXECUTE",
            fg_color="#238636",
            hover_color="#2ea043",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.on_plan_decision(True),
        )
        self.approve_btn.pack(side="left", padx=(0, 8))

        self.cancel_plan_btn = ctk.CTkButton(
            self.plan_btn_frame,
            text="✖ CANCEL",
            fg_color="#da3633",
            hover_color="#f85149",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.on_plan_decision(False),
        )
        self.cancel_plan_btn.pack(side="left")

        # Input Bar at Bottom
        self.input_frame = ctk.CTkFrame(self.chat_tab, height=50, fg_color="#121820")
        self.input_frame.pack(fill="x", side="bottom", padx=4, pady=6)

        # Push-to-Talk Mic Button
        self.mic_btn = ctk.CTkButton(
            self.input_frame,
            text="🎙️ Mic",
            width=68,
            height=38,
            fg_color="#21262d",
            hover_color="#30363d",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_mic_clicked,
        )
        self.mic_btn.pack(side="left", padx=(4, 6))

        # Text input box
        self.text_input = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Tell Jarvis what to do, or ask 'What is on my screen?'...",
            height=38,
            font=ctk.CTkFont(size=13),
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=4)
        self.text_input.bind("<Return>", lambda e: self.on_send_clicked())

        # Send Button
        self.send_btn = ctk.CTkButton(
            self.input_frame,
            text="Send",
            width=70,
            height=38,
            fg_color=_ACCENT_CYAN,
            text_color="#000000",
            hover_color="#00b0ff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_send_clicked,
        )
        self.send_btn.pack(side="left", padx=(6, 4))

    def _build_logs_tab(self) -> None:
        """Action log viewer."""
        top_ctrl = ctk.CTkFrame(self.logs_tab, fg_color="transparent")
        top_ctrl.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(
            top_ctrl,
            text="Action Execution Trail (computer_actions.log)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#c9d1d9",
        ).pack(side="left")

        ctk.CTkButton(
            top_ctrl,
            text="Clear View",
            width=80,
            height=28,
            fg_color="#21262d",
            command=self.clear_logs,
        ).pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            self.logs_tab,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="none",
            fg_color="#0d1117",
            text_color="#7ee787",
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_settings_tab(self) -> None:
        """Settings configuration panel."""
        scroll = ctk.CTkScrollableFrame(self.settings_tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14, pady=10)

        # Group 1: AI Engine
        lbl1 = ctk.CTkLabel(scroll, text="🧠 AI Model Settings", font=ctk.CTkFont(size=15, weight="bold"), text_color=_ACCENT_CYAN)
        lbl1.pack(anchor="w", pady=(8, 12))

        # Provider
        row0 = ctk.CTkFrame(scroll, fg_color="transparent")
        row0.pack(fill="x", pady=6)
        ctk.CTkLabel(row0, text="AI Provider:", width=160, anchor="w").pack(side="left")
        self.provider_entry = ctk.CTkOptionMenu(row0, values=["Ollama"], width=240)
        self.provider_entry.set(config.ai_provider)
        self.provider_entry.pack(side="left")

        # Ollama Host
        row1 = ctk.CTkFrame(scroll, fg_color="transparent")
        row1.pack(fill="x", pady=6)
        ctk.CTkLabel(row1, text="Ollama Endpoint:", width=160, anchor="w").pack(side="left")
        self.host_entry = ctk.CTkEntry(row1, width=240)
        self.host_entry.insert(0, config.ollama_host)
        self.host_entry.pack(side="left")

        # Planning Model
        row2 = ctk.CTkFrame(scroll, fg_color="transparent")
        row2.pack(fill="x", pady=6)
        ctk.CTkLabel(row2, text="Planning Model:", width=160, anchor="w").pack(side="left")
        self.model_entry = ctk.CTkEntry(row2, width=240)
        self.model_entry.insert(0, config.model_name)
        self.model_entry.pack(side="left")

        # Vision Model
        row3 = ctk.CTkFrame(scroll, fg_color="transparent")
        row3.pack(fill="x", pady=6)
        ctk.CTkLabel(row3, text="Vision Model:", width=160, anchor="w").pack(side="left")
        self.vision_entry = ctk.CTkEntry(row3, width=240)
        self.vision_entry.insert(0, config.vision_model)
        self.vision_entry.pack(side="left")

        # Timeout
        row4 = ctk.CTkFrame(scroll, fg_color="transparent")
        row4.pack(fill="x", pady=6)
        ctk.CTkLabel(row4, text="Timeout (seconds):", width=160, anchor="w").pack(side="left")
        self.timeout_entry = ctk.CTkEntry(row4, width=120)
        self.timeout_entry.insert(0, str(config.timeout_seconds))
        self.timeout_entry.pack(side="left")

        # Group 2: Behaviors
        lbl2 = ctk.CTkLabel(scroll, text="🛡️ Safety & Execution", font=ctk.CTkFont(size=15, weight="bold"), text_color=_ACCENT_CYAN)
        lbl2.pack(anchor="w", pady=(20, 12))

        self.ask_every_step_switch = ctk.CTkSwitch(scroll, text="Ask confirmation before sensitive actions (Recommended ON)")
        if config.ask_before_every_action:
            self.ask_every_step_switch.select()
        self.ask_every_step_switch.pack(anchor="w", pady=6)

        self.dry_run_switch = ctk.CTkSwitch(scroll, text="Dry-Run Mode (Simulate actions without mouse clicks)")
        if config.dry_run:
            self.dry_run_switch.select()
        self.dry_run_switch.pack(anchor="w", pady=6)

        self.voice_switch = ctk.CTkSwitch(scroll, text="Enable Voice Output (Spoken replies via TTS)")
        if config.voice_enabled:
            self.voice_switch.select()
        self.voice_switch.pack(anchor="w", pady=6)

        # Save Button
        self.save_btn = ctk.CTkButton(
            scroll,
            text="💾 Save Settings",
            fg_color="#238636",
            hover_color="#2ea043",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.save_settings,
        )
        self.save_btn.pack(anchor="w", pady=(24, 10))

    # ─────────────────────────────────────────────────────────────
    #  INTERACTION HANDLERS
    # ─────────────────────────────────────────────────────────────
    def update_status(self, state: str) -> None:
        """Update status line with color-coded dot."""
        colors = {
            "Idle": _ACCENT_GREEN,
            "Listening": "#e040fb",
            "Looking at screen": _ACCENT_CYAN,
            "Thinking": "#ffd600",
            "Waiting for your approval": "#ff9100",
            "Acting": "#ff6d00",
            "Stopped": _ACCENT_RED,
        }
        color = colors.get(state, "#8b949e")
        self.status_dot.configure(text_color=color)
        self.status_lbl.configure(text=state)

        # Animate mic button if listening
        if state == "Listening":
            self.is_listening = True
            self._pulse_mic()
        else:
            self.is_listening = False
            self.mic_btn.configure(fg_color="#21262d")

    def _pulse_mic(self) -> None:
        if not self.is_listening:
            self.mic_btn.configure(fg_color="#21262d")
            return
        colors = ["#b388ff", "#7c4dff", "#651fff", "#7c4dff"]
        self._mic_pulse_step = (self._mic_pulse_step + 1) % len(colors)
        self.mic_btn.configure(fg_color=colors[self._mic_pulse_step])
        self.after(250, self._pulse_mic)

    def add_chat_message(self, sender: str, text: str) -> None:
        """Append a message bubble to the chat scroll view."""
        is_user = sender.lower() == "you"
        frame_bg = _USER_BUBBLE if is_user else _JARVIS_BUBBLE
        align = "e" if is_user else "w"
        padx_side = (60, 8) if is_user else (8, 60)

        bubble_container = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        bubble_container.pack(fill="x", padx=4, pady=4, anchor=align)

        bubble = ctk.CTkFrame(bubble_container, fg_color=frame_bg, corner_radius=12)
        bubble.pack(side="right" if is_user else "left", padx=padx_side, pady=2)

        sender_lbl = ctk.CTkLabel(
            bubble,
            text=sender,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_ACCENT_CYAN if not is_user else "#a5d6ff",
        )
        sender_lbl.pack(anchor="w", padx=12, pady=(6, 2))

        msg_lbl = ctk.CTkLabel(
            bubble,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color="#f0f6fc",
            justify="left",
            wraplength=480,
        )
        msg_lbl.pack(anchor="w", padx=12, pady=(0, 8))

        # Auto-scroll to bottom
        self.after(50, lambda: self.chat_scroll._parent_canvas.yview_moveto(1.0))

    def show_plan_card(self, plan_text: str, is_risky: bool) -> None:
        """Display the proposed plan card with Approve and Cancel buttons."""
        if is_risky:
            self.plan_card.configure(border_color=_ACCENT_RED)
            self.plan_card_header.configure(text="⚠️ RISKY ACTION PLAN — CONFIRMATION REQUIRED", text_color=_ACCENT_RED)
        else:
            self.plan_card.configure(border_color=_ACCENT_CYAN)
            self.plan_card_header.configure(text="📋 PROPOSED PLAN FOR APPROVAL", text_color=_ACCENT_CYAN)

        self.plan_text_lbl.configure(text=plan_text)
        self.plan_card.pack(fill="x", padx=10, pady=8, before=self.input_frame)
        self.approve_btn.configure(state="normal")
        self.cancel_plan_btn.configure(state="normal")

    def on_plan_decision(self, approved: bool) -> None:
        """Handle Approve/Cancel button click."""
        self.approve_btn.configure(state="disabled")
        self.cancel_plan_btn.configure(state="disabled")
        self.plan_card.pack_forget()
        self.worker.approve_plan(approved)

    def update_screenshot_preview(self, img_bytes: bytes, window_title: str) -> None:
        """Update the sidebar screenshot thumbnail."""
        try:
            pil_img = Image.open(io.BytesIO(img_bytes))
            pil_img.thumbnail((236, 134), Image.LANCZOS)
            self._thumbnail_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
            self.preview_lbl.configure(image=self._thumbnail_img, text="")
            self.win_title_lbl.configure(text=f"Active: {window_title[:38]}...")
        except Exception as e:
            print(f"Thumbnail error: {e}")

    def append_log_entry(self, timestamp: str, step: int, action: str, result: str, success: bool) -> None:
        """Append log line to Action Log tab."""
        stat = "PASS" if success else "FAIL"
        entry = f"[{timestamp}] Step {step:<2} | {stat} | {action:<14} -> {result}\n"
        self.log_textbox.insert("end", entry)
        self.log_textbox.see("end")

    def clear_logs(self) -> None:
        self.log_textbox.delete("1.0", "end")

    def on_send_clicked(self) -> None:
        """Triggered by clicking Send or pressing Enter."""
        text = self.text_input.get().strip()
        if not text:
            return
        self.text_input.delete(0, "end")
        self.send_btn.configure(state="disabled")

        if text.lower() in ["what is on my screen", "what's on my screen", "describe screen"]:
            self.worker.describe_current_screen()
            self.send_btn.configure(state="normal")
            return

        self.worker.start_task(text)

    def on_mic_clicked(self) -> None:
        """Trigger push-to-talk voice input."""
        def _on_text(spoken_text: str):
            self.after(0, lambda: self._handle_voice_input(spoken_text))

        self.worker.record_voice(_on_text)

    def _handle_voice_input(self, text: str) -> None:
        if not text:
            return
        self.text_input.delete(0, "end")
        self.text_input.insert(0, text)
        self.on_send_clicked()

    def on_inspect_screen_clicked(self) -> None:
        self.worker.describe_current_screen()

    def on_emergency_stop_clicked(self) -> None:
        self.worker.stop()
        self.plan_card.pack_forget()
        self.send_btn.configure(state="normal")

    def on_task_completed(self) -> None:
        self.send_btn.configure(state="normal")

    def toggle_always_on_top(self) -> None:
        is_top = bool(self.topmost_switch.get())
        self.attributes("-topmost", is_top)
        config.always_on_top = is_top
        config.save()

    def save_settings(self) -> None:
        """Save settings from tab into config singleton and disk."""
        config.ai_provider = self.provider_entry.get()
        config.ollama_host = self.host_entry.get().strip()
        config.model_name = self.model_entry.get().strip()
        config.vision_model = self.vision_entry.get().strip()
        try:
            config.timeout_seconds = int(self.timeout_entry.get().strip())
        except ValueError:
            config.timeout_seconds = 120

        config.ask_before_every_action = bool(self.ask_every_step_switch.get())
        config.dry_run = bool(self.dry_run_switch.get())
        config.voice_enabled = bool(self.voice_switch.get())
        config.save()

        self.save_btn.configure(text="✅ Saved Successfully!")
        self.after(2000, lambda: self.save_btn.configure(text="💾 Save Settings"))

    # ─────────────────────────────────────────────────────────────
    #  SYSTEM TRAY SUPPORT
    # ─────────────────────────────────────────────────────────────
    def _setup_system_tray(self) -> None:
        try:
            import pystray
            from pystray import MenuItem as item

            # Generate default cyan dot icon
            icon_img = Image.new("RGBA", (32, 32), color=(13, 17, 23, 255))
            from PIL import ImageDraw
            d = ImageDraw.Draw(icon_img)
            d.ellipse((4, 4, 28, 28), fill=(0, 229, 255, 255))

            menu = (
                item("Show Jarvis", self._show_from_tray, default=True),
                item("Quit", self._quit_app),
            )
            self.tray_icon = pystray.Icon("jarvis_tray", icon_img, "Jarvis Screen Assistant", menu)

            # Protocol for minimizing to tray on window close
            self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        except Exception:
            self.tray_icon = None

    def _minimize_to_tray(self) -> None:
        if self.tray_icon:
            self.withdraw()
            t = threading.Thread(target=self.tray_icon.run, daemon=True)
            t.start()
        else:
            self.destroy()

    def _show_from_tray(self, icon=None, item=None) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.after(0, self.deiconify)

    def _quit_app(self, icon=None, item=None) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.worker._exit_listener = True
        self.destroy()
        sys.exit(0)


def main():
    app = JarvisApp()
    app.mainloop()


if __name__ == "__main__":
    main()
