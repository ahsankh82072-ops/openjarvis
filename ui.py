"""
ui.py — Jarvis Desktop Application with 3 Separated Modes and Hovering Voice HUD.
Modes:
  1. 💬 Chat Assistant: Messaging interface with text input & plan approval cards.
  2. 🎙️ Voice Talking Mode: Futuristic Iron Man arc-reactor logo hovering in the center with sound waves and live speech transcript.
  3. 🖥️ Screen & Action Control: Screen preview, real-time window inspection, and action logs.
"""

from __future__ import annotations

import argparse
import io
import math
import os
import sys
import threading
import time
import tkinter as tk
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config import config
from worker import JarvisWorker

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Theme Colors
_ACCENT_CYAN = "#00e5ff"
_ACCENT_MAGENTA = "#d500f9"
_ACCENT_GREEN = "#00e676"
_ACCENT_RED = "#ff1744"
_ACCENT_GOLD = "#ffd600"
_BG_DARK = "#0a0e14"
_CARD_BG = "#131922"
_USER_BUBBLE = "#1e3a5f"
_JARVIS_BUBBLE = "#152332"


class HoveringJarvisLogo(ctk.CTkCanvas):
    """Futuristic holographic Jarvis core that hovers in the center and pulses with speech."""

    def __init__(self, master, width=380, height=340, **kwargs):
        super().__init__(master, width=width, height=height, bg=_BG_DARK, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.hover_angle = 0.0
        self.pulse_phase = 0.0
        self.rotation_angle = 0.0
        self.state = "Idle"  # Idle, Listening, Thinking, Speaking, Stopped
        self._animating = True
        self._animate()

    def set_state(self, state: str) -> None:
        self.state = state

    def _animate(self) -> None:
        if not self._animating:
            return

        self.delete("all")
        self.hover_angle += 0.06
        self.pulse_phase += 0.12
        self.rotation_angle += 2.0

        # Hover offset (smooth floating bobbing effect)
        hover_y = math.sin(self.hover_angle) * 12.0
        cx = self.width / 2.0
        cy = (self.height / 2.0) + hover_y

        # Determine theme color based on status
        if self.state == "Listening":
            core_color = _ACCENT_MAGENTA
            ring_color = "#ea80fc"
            status_text = "🎙️ LISTENING..."
        elif self.state == "Thinking":
            core_color = _ACCENT_GOLD
            ring_color = "#ffe57f"
            status_text = "🧠 THINKING..."
        elif self.state == "Acting":
            core_color = "#ff6d00"
            ring_color = "#ffab40"
            status_text = "⚡ ACTING..."
        elif self.state == "Stopped":
            core_color = _ACCENT_RED
            ring_color = "#ff8a80"
            status_text = "🛑 STOPPED"
        else:
            core_color = _ACCENT_CYAN
            ring_color = "#80d8ff"
            status_text = "✨ STANDBY — SPEAK ALOUD"

        # 1. Outer Expanding Sound Waves (when listening or speaking)
        if self.state in ["Listening", "Acting"]:
            for i in range(3):
                wave_r = 90 + ((self.pulse_phase * 15 + i * 35) % 65)
                alpha_val = max(0, int(255 - (wave_r - 90) * 3.5))
                if wave_r > 90:
                    self.create_oval(
                        cx - wave_r, cy - wave_r, cx + wave_r, cy + wave_r,
                        outline=ring_color, width=1
                    )

        # 2. Outer Rotating Sci-Fi Ring
        outer_r = 110 + math.sin(self.pulse_phase) * 3
        self.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, outline="#1f2d3d", width=3)

        # Rotating Arc segments
        arc_start = self.rotation_angle % 360
        self.create_arc(
            cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
            start=arc_start, extent=70, outline=core_color, width=3, style="arc"
        )
        self.create_arc(
            cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
            start=(arc_start + 180) % 360, extent=70, outline=core_color, width=3, style="arc"
        )

        # 3. Middle Glow Ring
        mid_r = 75 + math.sin(self.pulse_phase * 1.5) * 4
        self.create_oval(cx - mid_r, cy - mid_r, cx + mid_r, cy + mid_r, outline=ring_color, width=2)

        # 4. Core Circle (Pulsing)
        core_r = 50 + math.sin(self.pulse_phase * 2) * 3
        self.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r, fill="#0d1722", outline=core_color, width=2)

        # 5. Center Arc Reactor Nodes
        node_r = 22
        self.create_oval(cx - node_r, cy - node_r, cx + node_r, cy + node_r, fill=core_color, outline="#ffffff", width=1)

        # 6. Central Brand Text
        self.create_text(
            cx, cy - 2,
            text="J.A.R.V.I.S.",
            fill="#ffffff",
            font=("Segoe UI", 11, "bold")
        )

        # 7. Bottom Status Caption
        self.create_text(
            cx, cy + 135,
            text=status_text,
            fill=core_color,
            font=("Segoe UI", 12, "bold")
        )

        self.after(35, self._animate)


class JarvisApp(ctk.CTk):
    """Modern Desktop Application for Jarvis with 3 Separated Modes."""

    def __init__(self, start_mode: str = "voice") -> None:
        super().__init__()

        self.title("J.A.R.V.I.S. — Autonomous Screen Assistant")
        self.geometry("1040x740")
        self.minsize(880, 620)
        self.configure(fg_color=_BG_DARK)

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

        self.current_mode = start_mode
        self._thumbnail_img: Optional[ctk.CTkImage] = None

        self._build_header()
        self._build_views()

        if config.always_on_top:
            self.attributes("-topmost", True)
            self.topmost_switch.select()

        # Switch to the requested initial mode
        self.switch_mode(start_mode)

        # Initial greet
        self.add_chat_message("Jarvis", "Jarvis online and ready, sir. Speak aloud or choose any mode above.")

    def _thread_safe(self, func):
        def _wrapper(*args, **kwargs):
            self.after(0, lambda: func(*args, **kwargs))
        return _wrapper

    # ─────────────────────────────────────────────────────────────
    #  TOP HEADER & MODE SELECTOR
    # ─────────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        self.header_frame = ctk.CTkFrame(self, height=58, corner_radius=0, fg_color="#0e141d")
        self.header_frame.pack(fill="x", side="top")

        # Logo
        ctk.CTkLabel(
            self.header_frame,
            text="⚡ J.A.R.V.I.S.",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=_ACCENT_CYAN,
        ).pack(side="left", padx=16, pady=10)

        # Status Dot & Label
        self.status_container = ctk.CTkFrame(self.header_frame, fg_color="#151e2b", corner_radius=14)
        self.status_container.pack(side="left", padx=8, pady=10)

        self.status_dot = ctk.CTkLabel(self.status_container, text="●", text_color=_ACCENT_GREEN, font=ctk.CTkFont(size=14))
        self.status_dot.pack(side="left", padx=(10, 4), pady=4)

        self.status_lbl = ctk.CTkLabel(
            self.status_container,
            text="Idle",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#c9d1d9",
        )
        self.status_lbl.pack(side="left", padx=(0, 12), pady=4)

        # 3 SEPARATED MODE BUTTONS (Center of Header)
        self.mode_frame = ctk.CTkFrame(self.header_frame, fg_color="#121822", corner_radius=12)
        self.mode_frame.pack(side="left", padx=20, pady=8)

        self.btn_mode_voice = ctk.CTkButton(
            self.mode_frame,
            text="🎙️ Voice Talking Mode",
            width=150,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_ACCENT_CYAN,
            text_color="#000000",
            command=lambda: self.switch_mode("voice"),
        )
        self.btn_mode_voice.pack(side="left", padx=4, pady=4)

        self.btn_mode_chat = ctk.CTkButton(
            self.mode_frame,
            text="💬 Chat Assistant",
            width=140,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e2633",
            text_color="#c9d1d9",
            command=lambda: self.switch_mode("chat"),
        )
        self.btn_mode_chat.pack(side="left", padx=4, pady=4)

        self.btn_mode_screen = ctk.CTkButton(
            self.mode_frame,
            text="🖥️ Screen Control",
            width=140,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e2633",
            text_color="#c9d1d9",
            command=lambda: self.switch_mode("screen"),
        )
        self.btn_mode_screen.pack(side="left", padx=4, pady=4)

        # Big Red Emergency STOP Button (Top Right)
        ctk.CTkButton(
            self.header_frame,
            text="🚨 EMERGENCY STOP",
            fg_color="#d32f2f",
            hover_color="#b71c1c",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            command=self.on_emergency_stop_clicked,
        ).pack(side="right", padx=14, pady=10)

        # Pin On Top
        self.topmost_switch = ctk.CTkSwitch(
            self.header_frame,
            text="Pin on top",
            font=ctk.CTkFont(size=12),
            command=self.toggle_always_on_top,
        )
        self.topmost_switch.pack(side="right", padx=10, pady=10)

    # ─────────────────────────────────────────────────────────────
    #  BUILD THE 3 SEPARATED VIEWS
    # ─────────────────────────────────────────────────────────────
    def _build_views(self) -> None:
        self.view_container = ctk.CTkFrame(self, fg_color="transparent")
        self.view_container.pack(fill="both", expand=True, padx=10, pady=10)

        # VIEW 1: VOICE TALKING MODE (Center Hovering Logo HUD)
        self.view_voice = ctk.CTkFrame(self.view_container, fg_color=_BG_DARK)
        self._build_voice_mode_view()

        # VIEW 2: CHAT ASSISTANT
        self.view_chat = ctk.CTkFrame(self.view_container, fg_color=_BG_DARK)
        self._build_chat_view()

        # VIEW 3: SCREEN & ACTION CONTROL
        self.view_screen = ctk.CTkFrame(self.view_container, fg_color=_BG_DARK)
        self._build_screen_control_view()

    # ─────────────────────────────────────────────────────────────
    #  1. VOICE TALKING MODE VIEW (CENTER HOVERING LOGO)
    # ─────────────────────────────────────────────────────────────
    def _build_voice_mode_view(self) -> None:
        # Center Hovering Arc-Reactor Logo Canvas
        self.logo_canvas = HoveringJarvisLogo(self.view_voice, width=420, height=360)
        self.logo_canvas.pack(pady=(15, 5))

        # Big Voice Push-to-Talk Button
        self.voice_action_btn = ctk.CTkButton(
            self.view_voice,
            text="🎙️ PRESS & SPEAK (OR SAY 'HEY JARVIS')",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=_ACCENT_CYAN,
            text_color="#000000",
            hover_color="#00b0ff",
            height=46,
            width=360,
            command=self.on_voice_talk_clicked,
        )
        self.voice_action_btn.pack(pady=8)

        # Live Transcript Dialogue Card
        self.voice_card = ctk.CTkFrame(self.view_voice, fg_color=_CARD_BG, corner_radius=12, width=640)
        self.voice_card.pack(fill="x", padx=60, pady=12)

        self.voice_user_text = ctk.CTkLabel(
            self.voice_card,
            text="You: Speak a command like 'open youtube and play music' or 'what is on my screen'...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#80d8ff",
            wraplength=600,
            justify="center",
        )
        self.voice_user_text.pack(padx=20, pady=(12, 6))

        self.voice_jarvis_text = ctk.CTkLabel(
            self.voice_card,
            text="Jarvis: Standing by for your instructions, sir.",
            font=ctk.CTkFont(size=13),
            text_color="#c9d1d9",
            wraplength=600,
            justify="center",
        )
        self.voice_jarvis_text.pack(padx=20, pady=(0, 14))

    # ─────────────────────────────────────────────────────────────
    #  2. CHAT ASSISTANT VIEW
    # ─────────────────────────────────────────────────────────────
    def _build_chat_view(self) -> None:
        # Chat Messages Scroll Area
        self.chat_scroll = ctk.CTkScrollableFrame(self.view_chat, fg_color="transparent")
        self.chat_scroll.pack(fill="both", expand=True, padx=10, pady=4)

        # Plan Approval Card Container
        self.plan_card = ctk.CTkFrame(self.view_chat, fg_color="#182230", corner_radius=10, border_width=2, border_color=_ACCENT_CYAN)

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
            wraplength=620,
        )
        self.plan_text_lbl.pack(anchor="w", padx=14, pady=4)

        btn_box = ctk.CTkFrame(self.plan_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=14, pady=(6, 10))

        self.approve_btn = ctk.CTkButton(
            btn_box,
            text="✔ APPROVE & EXECUTE",
            fg_color="#238636",
            hover_color="#2ea043",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.on_plan_decision(True),
        )
        self.approve_btn.pack(side="left", padx=(0, 8))

        self.cancel_plan_btn = ctk.CTkButton(
            btn_box,
            text="✖ CANCEL",
            fg_color="#da3633",
            hover_color="#f85149",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=32,
            command=lambda: self.on_plan_decision(False),
        )
        self.cancel_plan_btn.pack(side="left")

        # Chat Input Bar
        self.input_frame = ctk.CTkFrame(self.view_chat, height=52, fg_color="#121822")
        self.input_frame.pack(fill="x", side="bottom", padx=10, pady=6)

        self.text_input = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Tell Jarvis what to do, or ask 'What is on my screen?'...",
            height=38,
            font=ctk.CTkFont(size=13),
        )
        self.text_input.pack(side="left", fill="x", expand=True, padx=6)
        self.text_input.bind("<Return>", lambda e: self.on_send_clicked())

        self.send_btn = ctk.CTkButton(
            self.input_frame,
            text="Send",
            width=75,
            height=38,
            fg_color=_ACCENT_CYAN,
            text_color="#000000",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_send_clicked,
        )
        self.send_btn.pack(side="left", padx=4)

    # ─────────────────────────────────────────────────────────────
    #  3. SCREEN & ACTION CONTROL VIEW
    # ─────────────────────────────────────────────────────────────
    def _build_screen_control_view(self) -> None:
        paned = ctk.CTkFrame(self.view_screen, fg_color="transparent")
        paned.pack(fill="both", expand=True)

        # Left Column: Big Screen Preview & Trigger
        left_col = ctk.CTkFrame(paned, width=380, fg_color=_CARD_BG, corner_radius=12)
        left_col.pack(side="left", fill="y", padx=(0, 8), pady=4)
        left_col.pack_propagate(False)

        ctk.CTkLabel(left_col, text="🖥️ LIVE SCREEN VIEW", font=ctk.CTkFont(size=14, weight="bold"), text_color=_ACCENT_CYAN).pack(anchor="w", padx=14, pady=12)

        self.screen_preview_box = ctk.CTkLabel(
            left_col,
            text="Click 'Inspect Screen' to capture",
            width=350,
            height=200,
            fg_color="#0d1117",
            corner_radius=8,
            text_color="#8b949e",
        )
        self.screen_preview_box.pack(padx=14, pady=6)

        self.screen_win_lbl = ctk.CTkLabel(
            left_col, text="Active Window: Unknown", font=ctk.CTkFont(size=11), text_color="#8b949e", wraplength=340, justify="left"
        )
        self.screen_win_lbl.pack(anchor="w", padx=14, pady=(4, 10))

        ctk.CTkButton(
            left_col,
            text="👀 What's on my screen?",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#006699",
            hover_color="#0088cc",
            height=36,
            command=self.worker.describe_current_screen,
        ).pack(fill="x", padx=14, pady=6)

        # Quick Task Buttons
        ctk.CTkLabel(left_col, text="⚡ Quick Shortcuts:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#80d8ff").pack(anchor="w", padx=14, pady=(16, 6))

        quick_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        quick_frame.pack(fill="x", padx=14)

        ctk.CTkButton(quick_frame, text="Notepad", width=75, height=28, command=lambda: self.worker.start_task("open notepad")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="Chrome", width=75, height=28, command=lambda: self.worker.start_task("open chrome")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="Calculator", width=75, height=28, command=lambda: self.worker.start_task("open calculator")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="Calendar", width=75, height=28, command=lambda: self.worker.start_task("open calendar")).pack(side="left", padx=2)

        # Right Column: Action Log & Audit Trail
        right_col = ctk.CTkFrame(paned, fg_color=_CARD_BG, corner_radius=12)
        right_col.pack(side="left", fill="both", expand=True, pady=4)

        log_head = ctk.CTkFrame(right_col, fg_color="transparent")
        log_head.pack(fill="x", padx=14, pady=10)

        ctk.CTkLabel(log_head, text="📜 ACTION AUDIT TRAIL", font=ctk.CTkFont(size=14, weight="bold"), text_color=_ACCENT_CYAN).pack(side="left")
        ctk.CTkButton(log_head, text="Clear Logs", width=80, height=26, fg_color="#21262d", command=self.clear_logs).pack(side="right")

        self.log_textbox = ctk.CTkTextbox(right_col, font=ctk.CTkFont(family="Consolas", size=12), wrap="none", fg_color="#0a0e14", text_color="#7ee787")
        self.log_textbox.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    # ─────────────────────────────────────────────────────────────
    #  MODE SWITCHING LOGIC
    # ─────────────────────────────────────────────────────────────
    def switch_mode(self, mode: str) -> None:
        """Switch between the 3 clearly separated modes."""
        self.current_mode = mode

        # Hide all views
        self.view_voice.pack_forget()
        self.view_chat.pack_forget()
        self.view_screen.pack_forget()

        # Reset button styles
        self.btn_mode_voice.configure(fg_color="#1e2633", text_color="#c9d1d9")
        self.btn_mode_chat.configure(fg_color="#1e2633", text_color="#c9d1d9")
        self.btn_mode_screen.configure(fg_color="#1e2633", text_color="#c9d1d9")

        if mode == "voice":
            self.view_voice.pack(fill="both", expand=True)
            self.btn_mode_voice.configure(fg_color=_ACCENT_CYAN, text_color="#000000")
        elif mode == "chat":
            self.view_chat.pack(fill="both", expand=True)
            self.btn_mode_chat.configure(fg_color=_ACCENT_CYAN, text_color="#000000")
        elif mode == "screen":
            self.view_screen.pack(fill="both", expand=True)
            self.btn_mode_screen.configure(fg_color=_ACCENT_CYAN, text_color="#000000")

    # ─────────────────────────────────────────────────────────────
    #  EVENT HANDLERS & CALLBACKS
    # ─────────────────────────────────────────────────────────────
    def update_status(self, state: str) -> None:
        colors = {
            "Idle": _ACCENT_GREEN,
            "Listening": _ACCENT_MAGENTA,
            "Looking at screen": _ACCENT_CYAN,
            "Thinking": _ACCENT_GOLD,
            "Waiting for your approval": "#ff9100",
            "Acting": "#ff6d00",
            "Stopped": _ACCENT_RED,
        }
        color = colors.get(state, "#8b949e")
        self.status_dot.configure(text_color=color)
        self.status_lbl.configure(text=state)
        self.logo_canvas.set_state(state)

    def add_chat_message(self, sender: str, text: str) -> None:
        is_user = sender.lower() == "you"
        frame_bg = _USER_BUBBLE if is_user else _JARVIS_BUBBLE
        align = "e" if is_user else "w"
        padx_side = (60, 8) if is_user else (8, 60)

        bubble_container = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        bubble_container.pack(fill="x", padx=4, pady=4, anchor=align)

        bubble = ctk.CTkFrame(bubble_container, fg_color=frame_bg, corner_radius=12)
        bubble.pack(side="right" if is_user else "left", padx=padx_side, pady=2)

        ctk.CTkLabel(
            bubble,
            text=sender,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_ACCENT_CYAN if not is_user else "#a5d6ff",
        ).pack(anchor="w", padx=12, pady=(6, 2))

        ctk.CTkLabel(
            bubble,
            text=text,
            font=ctk.CTkFont(size=13),
            text_color="#f0f6fc",
            justify="left",
            wraplength=500,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # Also update Voice HUD card
        if is_user:
            self.voice_user_text.configure(text=f"You: {text}")
        else:
            self.voice_jarvis_text.configure(text=f"Jarvis: {text[:140]}...")

        self.after(50, lambda: self.chat_scroll._parent_canvas.yview_moveto(1.0))

    def show_plan_card(self, plan_text: str, is_risky: bool) -> None:
        if is_risky:
            self.plan_card.configure(border_color=_ACCENT_RED)
            self.plan_card_header.configure(text="⚠️ RISKY ACTION PLAN — CONFIRMATION REQUIRED", text_color=_ACCENT_RED)
        else:
            self.plan_card.configure(border_color=_ACCENT_CYAN)
            self.plan_card_header.configure(text="📋 PROPOSED PLAN FOR APPROVAL", text_color=_ACCENT_CYAN)

        self.plan_text_lbl.configure(text=plan_text)
        self.plan_card.pack(fill="x", padx=10, pady=8, before=self.input_frame)

    def on_plan_decision(self, approved: bool) -> None:
        self.plan_card.pack_forget()
        self.worker.approve_plan(approved)

    def update_screenshot_preview(self, img_bytes: bytes, window_title: str) -> None:
        try:
            pil_img = Image.open(io.BytesIO(img_bytes))
            pil_img.thumbnail((350, 195), Image.LANCZOS)
            self._thumbnail_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=pil_img.size)
            self.screen_preview_box.configure(image=self._thumbnail_img, text="")
            self.screen_win_lbl.configure(text=f"Active: {window_title[:45]}...")
        except Exception as e:
            print(f"Thumbnail error: {e}")

    def append_log_entry(self, timestamp: str, step: int, action: str, result: str, success: bool) -> None:
        stat = "PASS" if success else "FAIL"
        entry = f"[{timestamp}] Step {step:<2} | {stat} | {action:<16} -> {result}\n"
        self.log_textbox.insert("end", entry)
        self.log_textbox.see("end")

    def clear_logs(self) -> None:
        self.log_textbox.delete("1.0", "end")

    def on_send_clicked(self) -> None:
        text = self.text_input.get().strip()
        if not text:
            return
        self.text_input.delete(0, "end")
        self.worker.start_task(text)

    def on_voice_talk_clicked(self) -> None:
        """Triggered from Talking Mode center button."""
        def _on_heard(spoken: str):
            self.after(0, lambda: self.worker.start_task(spoken))

        self.worker.record_voice(_on_heard)

    def on_emergency_stop_clicked(self) -> None:
        self.worker.stop()
        self.plan_card.pack_forget()

    def on_task_completed(self) -> None:
        pass

    def toggle_always_on_top(self) -> None:
        is_top = bool(self.topmost_switch.get())
        self.attributes("-topmost", is_top)
        config.always_on_top = is_top
        config.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["voice", "chat", "screen"], default="voice")
    args = parser.parse_args()

    app = JarvisApp(start_mode=args.mode)
    app.mainloop()


if __name__ == "__main__":
    main()
