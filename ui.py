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
from gemini_live_engine import GeminiLiveEngine
from live_ui_panel import GeminiLivePanel

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Ultra-Premium Minimalist Palette (Obsidian + Neon Cyan + Rose Accents)
_ACCENT_CYAN = "#00f0ff"
_ACCENT_MAGENTA = "#d946ef"
_ACCENT_GREEN = "#10b981"
_ACCENT_RED = "#ef4444"
_ACCENT_GOLD = "#fbbf24"
_BG_DARK = "#05070a"
_HEADER_BG = "#080c14"
_CARD_BG = "#0c111c"
_CARD_BORDER = "#162032"
_USER_BUBBLE = "#0d2033"
_JARVIS_BUBBLE = "#0f1522"


class GlowingOrbVisualizer(ctk.CTkCanvas):
    """
    Cinematic undulating neon ribbon & orbital particle arcs visualizer.
    Matches the user's reference design with fluid wave harmonics and concentric spinning arcs.
    """

    def __init__(self, master, width=440, height=380, **kwargs):
        super().__init__(master, width=width, height=height, bg=_BG_DARK, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.angle = 0.0
        self.state = "Idle"  # Idle, Listening, Thinking, Acting, Stopped
        self._animating = True
        self._animate()

    def set_state(self, state: str) -> None:
        self.state = state

    def _animate(self) -> None:
        if not self._animating:
            return

        self.delete("all")
        cx = self.width / 2.0
        cy = self.height / 2.0

        # Dynamic speed and wave amplitude based on state
        if self.state == "Listening":
            speed_mult = 1.5
            ribbon_amp = 18.0
            pulse = math.sin(self.angle * 4.0) * 8.0
            ribbon_color = "#00f0ff"
            glow_aura = "#083344"
            core_shades = ["#ff3366", "#ff2a5f", "#f43f5e", "#fb7185", "#be123c"]
        elif self.state == "Thinking":
            speed_mult = 2.4
            ribbon_amp = 14.0
            pulse = math.sin(self.angle * 6.0) * 6.0
            ribbon_color = "#38bdf8"
            glow_aura = "#0c4a6e"
            core_shades = ["#fbbf24", "#f59e0b", "#f43f5e", "#ff2a5f", "#d97706"]
        elif self.state == "Acting":
            speed_mult = 1.8
            ribbon_amp = 16.0
            pulse = math.sin(self.angle * 3.0) * 7.0
            ribbon_color = "#22d3ee"
            glow_aura = "#155e75"
            core_shades = ["#ff4d6d", "#f43f5e", "#e11d48", "#be123c", "#fb7185"]
        elif self.state == "Stopped":
            speed_mult = 0.3
            ribbon_amp = 6.0
            pulse = 0.0
            ribbon_color = "#ef4444"
            glow_aura = "#450a0a"
            core_shades = ["#7f1d1d", "#991b1b", "#b91c1c", "#dc2626", "#ef4444"]
        else:  # Idle
            speed_mult = 1.0
            ribbon_amp = 11.0
            pulse = math.sin(self.angle * 1.5) * 4.0
            ribbon_color = "#00f0ff"
            glow_aura = "#041d2d"
            core_shades = ["#ff3366", "#ff4d6d", "#f43f5e", "#c9184a", "#800f2f"]

        self.angle += 0.035 * speed_mult

        # 1. Background subtle plasma auras
        canvas_r = 135 + pulse * 0.5
        self.create_oval(cx - canvas_r, cy - canvas_r, cx + canvas_r, cy + canvas_r, fill=glow_aura, outline="")
        self.create_oval(cx - 100, cy - 100, cx + 100, cy + 100, fill="#12060a", outline="")

        # 2. Concentric Crimson/Coral Orbital Arcs (from user reference image)
        arc_configs = [
            (62, self.angle * 35, 130, core_shades[0], 1.6),
            (72, -self.angle * 45 + 50, 100, core_shades[1], 1.2),
            (82, self.angle * 28 + 110, 150, core_shades[2], 1.8),
            (90, -self.angle * 38 + 190, 85, core_shades[3], 1.1),
            (99, self.angle * 22 + 260, 165, core_shades[1], 1.5),
            (108, -self.angle * 32 + 80, 95, core_shades[4], 1.2),
            (117, self.angle * 42 + 20, 120, core_shades[2], 1.4),
            (126, -self.angle * 18 + 150, 140, core_shades[0], 1.0),
        ]

        for radius, start, extent, color, width in arc_configs:
            self.create_arc(
                cx - radius, cy - radius, cx + radius, cy + radius,
                start=start % 360, extent=extent,
                style="arc", outline=color, width=width
            )

        # 3. Fluid Undulating Neon Cyan Ribbon (Organic wave harmonics)
        num_pts = 72
        cyan_pts = []
        base_r = 95 + pulse
        amp1 = ribbon_amp * math.sin(self.angle * 1.8)
        amp2 = (ribbon_amp * 0.7) * math.cos(self.angle * 2.4)
        amp3 = (ribbon_amp * 0.4) * math.sin(self.angle * 3.2)

        for i in range(num_pts + 1):
            th = i * 2 * math.pi / num_pts
            # 3-lobed + 2-lobed + 5-lobed fluid harmonic wave
            r = base_r + amp1 * math.sin(3 * th + self.angle * 2) + amp2 * math.cos(2 * th - self.angle * 1.4) + amp3 * math.sin(5 * th + self.angle)
            px = cx + r * math.cos(th)
            py = cy + r * math.sin(th)
            cyan_pts.extend([px, py])

        # Layered neon ribbon glow (from diffuse blur to razor-sharp core filament)
        self.create_line(cyan_pts, smooth=True, fill="#042f40", width=12)
        self.create_line(cyan_pts, smooth=True, fill="#0891b2", width=7)
        self.create_line(cyan_pts, smooth=True, fill=ribbon_color, width=3.2)
        self.create_line(cyan_pts, smooth=True, fill="#f0fdfa", width=1.2)

        # 4. Inner Deep Core Void
        self.create_oval(cx - 44, cy - 44, cx + 44, cy + 44, fill="#05070a", outline="#1c0a12", width=1.5)

        self.after(35, self._animate)


# Alias for backward compatibility
HoveringJarvisLogo = GlowingOrbVisualizer


class JarvisApp(ctk.CTk):
    """Modern Desktop Application for Jarvis with 3 Separated Modes."""

    def __init__(self, start_mode: str = "voice") -> None:
        super().__init__()

        self.title("Jarvis — Autonomous Screen Assistant")
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
                "on_activate_window": self._thread_safe(self.on_activate_window),
            }
        )

        self.live_engine = GeminiLiveEngine(
            callbacks={
                "on_status": self._thread_safe(self.update_status),
                "on_chat": self._thread_safe(self.add_chat_message),
                "on_log": self._thread_safe(self.append_log_entry),
            }
        )
        self.live_panel: Optional[GeminiLivePanel] = None

        self.current_mode = start_mode
        self._thumbnail_img: Optional[ctk.CTkImage] = None

        self._build_header()
        self._build_views()

        if config.always_on_top:
            self.attributes("-topmost", True)
            self.topmost_switch.select()

        # Switch to the requested initial mode
        self.switch_mode(start_mode)

        # Spacebar Push-To-Talk Bindings
        self._space_is_held = False
        self.bind_all("<KeyPress-space>", self._on_space_press)
        self.bind_all("<KeyRelease-space>", self._on_space_release)

    def _thread_safe(self, func):
        def _wrapper(*args, **kwargs):
            self.after(0, lambda: func(*args, **kwargs))
        return _wrapper

    # ─────────────────────────────────────────────────────────────
    #  TOP HEADER & MODE SELECTOR
    # ─────────────────────────────────────────────────────────────
    def _build_header(self) -> None:
        self.header_frame = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color=_HEADER_BG)
        self.header_frame.pack(fill="x", side="top")

        # Minimalist Glowing Spark Icon
        logo_box = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        logo_box.pack(side="left", padx=(16, 8), pady=8)

        ctk.CTkLabel(
            logo_box,
            text="⚡",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=_ACCENT_CYAN,
        ).pack(side="left")

        # Sleek Status Pill
        self.status_container = ctk.CTkFrame(self.header_frame, fg_color="#0e1524", corner_radius=12)
        self.status_container.pack(side="left", padx=6, pady=10)

        self.status_dot = ctk.CTkLabel(self.status_container, text="●", text_color=_ACCENT_GREEN, font=ctk.CTkFont(size=12))
        self.status_dot.pack(side="left", padx=(8, 4), pady=2)

        self.status_lbl = ctk.CTkLabel(
            self.status_container,
            text="Idle",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#94a3b8",
        )
        self.status_lbl.pack(side="left", padx=(0, 10), pady=2)

        # Segmented Pill Mode Selector
        self.mode_frame = ctk.CTkFrame(self.header_frame, fg_color="#0e1524", corner_radius=16)
        self.mode_frame.pack(side="left", padx=24, pady=8)

        self.btn_mode_voice = ctk.CTkButton(
            self.mode_frame,
            text="🎙️ Voice",
            width=88,
            height=30,
            corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=_ACCENT_CYAN,
            text_color="#05070a",
            hover_color="#38bdf8",
            command=lambda: self.switch_mode("voice"),
        )
        self.btn_mode_voice.pack(side="left", padx=3, pady=3)

        self.btn_mode_chat = ctk.CTkButton(
            self.mode_frame,
            text="💬 Chat",
            width=84,
            height=30,
            corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            text_color="#94a3b8",
            hover_color="#131b2e",
            command=lambda: self.switch_mode("chat"),
        )
        self.btn_mode_chat.pack(side="left", padx=3, pady=3)

        self.btn_mode_screen = ctk.CTkButton(
            self.mode_frame,
            text="🖥️ Screen",
            width=92,
            height=30,
            corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            text_color="#94a3b8",
            hover_color="#131b2e",
            command=lambda: self.switch_mode("screen"),
        )
        self.btn_mode_screen.pack(side="left", padx=3, pady=3)

        self.btn_mode_live = ctk.CTkButton(
            self.mode_frame,
            text="⚡ Live",
            width=82,
            height=30,
            corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#102538",
            border_color=_ACCENT_CYAN,
            border_width=1,
            text_color=_ACCENT_CYAN,
            hover_color="#1c3b54",
            command=self.open_live_panel,
        )
        self.btn_mode_live.pack(side="left", padx=3, pady=3)

        self.btn_mode_settings = ctk.CTkButton(
            self.mode_frame,
            text="⚙️ Settings",
            width=96,
            height=30,
            corner_radius=14,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            text_color="#94a3b8",
            hover_color="#131b2e",
            command=lambda: self.switch_mode("settings"),
        )
        self.btn_mode_settings.pack(side="left", padx=3, pady=3)

        # Minimalist Emergency STOP Pill (Top Right)
        ctk.CTkButton(
            self.header_frame,
            text="🚨 STOP",
            width=78,
            height=28,
            corner_radius=14,
            fg_color="#271015",
            hover_color="#450a0a",
            border_color="#ef4444",
            border_width=1,
            text_color="#f87171",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.on_emergency_stop_clicked,
        ).pack(side="right", padx=14, pady=10)

        # Pin On Top
        self.topmost_switch = ctk.CTkSwitch(
            self.header_frame,
            text="Pin on top",
            font=ctk.CTkFont(size=11),
            command=self.toggle_always_on_top,
        )
        self.topmost_switch.pack(side="right", padx=8, pady=10)

    # ─────────────────────────────────────────────────────────────
    #  BUILD THE 4 SEPARATED VIEWS
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

        # VIEW 4: SETTINGS & INTEGRATIONS
        self.view_settings = ctk.CTkScrollableFrame(self.view_container, fg_color=_BG_DARK)
        self._build_settings_view()

    # ─────────────────────────────────────────────────────────────
    #  1. VOICE TALKING MODE VIEW (CENTER HOVERING LOGO)
    # ─────────────────────────────────────────────────────────────
    def _build_voice_mode_view(self) -> None:
        # Center Glowing Orb Visualizer Canvas (matching user reference design)
        self.logo_canvas = GlowingOrbVisualizer(self.view_voice, width=440, height=380)
        self.logo_canvas.pack(pady=(10, 4))

        # Minimalist Push-to-Talk Pill Button
        self.voice_action_btn = ctk.CTkButton(
            self.view_voice,
            text="🎙️ PRESS & HOLD SPACEBAR TO SPEAK",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0a192f",
            border_color="#00f0ff",
            border_width=1.5,
            text_color="#00f0ff",
            hover_color="#102e4d",
            height=42,
            width=340,
            corner_radius=21,
        )
        self.voice_action_btn.pack(pady=6)

        # Mouse click-and-hold bindings (also works by clicking & holding the button!)
        self.voice_action_btn.bind("<ButtonPress-1>", lambda e: self._on_space_press(None))
        self.voice_action_btn.bind("<ButtonRelease-1>", lambda e: self._on_space_release(None))

        # Live Transcript Dialogue Card
        self.voice_card = ctk.CTkFrame(
            self.view_voice, fg_color=_CARD_BG, border_color=_CARD_BORDER, border_width=1, corner_radius=16, width=640
        )
        self.voice_card.pack(fill="x", padx=80, pady=10)

        self.voice_user_text = ctk.CTkLabel(
            self.voice_card,
            text="You: Speak aloud or hold Spacebar...",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8",
            wraplength=600,
            justify="center",
        )
        self.voice_user_text.pack(padx=20, pady=(12, 4))

        self.voice_jarvis_text = ctk.CTkLabel(
            self.voice_card,
            text="Jarvis: Standing by for your instructions, sir",
            font=ctk.CTkFont(size=13),
            text_color="#f8fafc",
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
            placeholder_text="Tell Jarvis what to do, or ask 'What is on my screen?'",
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

        # Title & Active Badge
        head_box = ctk.CTkFrame(left_col, fg_color="transparent")
        head_box.pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkLabel(head_box, text="🖥️ SCREEN SHARE & FOLLOW", font=ctk.CTkFont(size=13, weight="bold"), text_color=_ACCENT_CYAN).pack(side="left")

        ctk.CTkLabel(
            head_box,
            text="🟢 LIVE ACTIVE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_ACCENT_GREEN,
            fg_color="#102b1d",
            corner_radius=6,
            padx=6,
            pady=2,
        ).pack(side="right")

        # Instruction Card
        guide_box = ctk.CTkFrame(left_col, fg_color="#101824", corner_radius=8)
        guide_box.pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(
            guide_box,
            text="🎙️ Switch to Google or any app and speak aloud:\n\"Jarvis, search for...\" • \"Jarvis, scroll down\"\n\"Jarvis, open YouTube\" • \"Jarvis, do this\"",
            font=ctk.CTkFont(size=11),
            text_color="#80d8ff",
            justify="center",
        ).pack(padx=8, pady=6)

        self.screen_preview_box = ctk.CTkLabel(
            left_col,
            text="Click 'Inspect Screen' to capture",
            width=350,
            height=175,
            fg_color="#0d1117",
            corner_radius=8,
            text_color="#8b949e",
        )
        self.screen_preview_box.pack(padx=14, pady=4)

        self.screen_win_lbl = ctk.CTkLabel(
            left_col, text="Active Window: Unknown", font=ctk.CTkFont(size=11), text_color="#8b949e", wraplength=340, justify="left"
        )
        self.screen_win_lbl.pack(anchor="w", padx=14, pady=(2, 6))

        ctk.CTkButton(
            left_col,
            text="👀 What's on my screen?",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#006699",
            hover_color="#0088cc",
            height=32,
            command=self.worker.describe_current_screen,
        ).pack(fill="x", padx=14, pady=4)

        # Quick In-App Navigation Controls
        ctk.CTkLabel(left_col, text="⚡ In-App Navigation:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#80d8ff").pack(anchor="w", padx=14, pady=(8, 2))

        nav_frame1 = ctk.CTkFrame(left_col, fg_color="transparent")
        nav_frame1.pack(fill="x", padx=14, pady=2)

        ctk.CTkButton(nav_frame1, text="📜 Scroll Down", width=110, height=26, command=lambda: self.worker.start_task("scroll down")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame1, text="📜 Scroll Up", width=110, height=26, command=lambda: self.worker.start_task("scroll up")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame1, text="🔄 Refresh", width=110, height=26, command=lambda: self.worker.start_task("refresh")).pack(side="left", padx=2)

        nav_frame2 = ctk.CTkFrame(left_col, fg_color="transparent")
        nav_frame2.pack(fill="x", padx=14, pady=2)

        ctk.CTkButton(nav_frame2, text="➕ New Tab", width=110, height=26, command=lambda: self.worker.start_task("new tab")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame2, text="❌ Close Tab", width=110, height=26, command=lambda: self.worker.start_task("close tab")).pack(side="left", padx=2)
        ctk.CTkButton(nav_frame2, text="⬅️ Back", width=110, height=26, command=lambda: self.worker.start_task("go back")).pack(side="left", padx=2)

        # Quick App Shortcuts
        ctk.CTkLabel(left_col, text="🚀 Quick App Launch:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#80d8ff").pack(anchor="w", padx=14, pady=(6, 2))

        quick_frame = ctk.CTkFrame(left_col, fg_color="transparent")
        quick_frame.pack(fill="x", padx=14, pady=2)

        ctk.CTkButton(quick_frame, text="Chrome", width=80, height=26, command=lambda: self.worker.start_task("open chrome")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="YouTube", width=80, height=26, command=lambda: self.worker.start_task("open youtube")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="Notepad", width=80, height=26, command=lambda: self.worker.start_task("open notepad")).pack(side="left", padx=2)
        ctk.CTkButton(quick_frame, text="Calc", width=80, height=26, command=lambda: self.worker.start_task("open calculator")).pack(side="left", padx=2)

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
    #  4. SETTINGS & INTEGRATIONS VIEW
    # ─────────────────────────────────────────────────────────────
    def _build_settings_view(self) -> None:
        # Title Header
        title_box = ctk.CTkFrame(self.view_settings, fg_color="transparent")
        title_box.pack(fill="x", padx=16, pady=(8, 12))

        ctk.CTkLabel(
            title_box,
            text="⚙️ Integrations & Autonomous Control",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=_ACCENT_CYAN,
        ).pack(side="left")

        # ── 1. AUTONOMOUS FULL PC CONTROL CARD ───────────────────
        ctrl_card = ctk.CTkFrame(self.view_settings, fg_color=_CARD_BG, corner_radius=12)
        ctrl_card.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(
            ctrl_card,
            text="⚡ Autonomous PC Control",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#80d8ff",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            ctrl_card,
            text="When Full PC Control is enabled, Jarvis directly executes safe tasks and checks your apps without stopping for button approvals.",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        sw_row = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        sw_row.pack(fill="x", padx=16, pady=(0, 14))

        self.sw_full_control = ctk.CTkSwitch(
            sw_row,
            text="Full Autonomous PC Control (Direct execution without pauses)",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.sw_full_control.pack(side="left", padx=(0, 20))
        if config.full_pc_control:
            self.sw_full_control.select()
        else:
            self.sw_full_control.deselect()

        self.sw_voice = ctk.CTkSwitch(
            sw_row,
            text="Voice Output (Speak aloud answers)",
            font=ctk.CTkFont(size=12),
        )
        self.sw_voice.pack(side="left")
        if config.voice_enabled:
            self.sw_voice.select()
        else:
            self.sw_voice.deselect()

        # ── 2. GMAIL INTEGRATION CARD ────────────────────────────
        gmail_card = ctk.CTkFrame(self.view_settings, fg_color=_CARD_BG, corner_radius=12)
        gmail_card.pack(fill="x", padx=16, pady=6)

        g_head = ctk.CTkFrame(gmail_card, fg_color="transparent")
        g_head.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            g_head,
            text="📧 Gmail Integration",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#80d8ff",
        ).pack(side="left")

        self.gmail_status_lbl = ctk.CTkLabel(
            g_head,
            text="● Attached" if (config.gmail_address and config.gmail_app_password) else "○ Not Attached",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_ACCENT_GREEN if (config.gmail_address and config.gmail_app_password) else "#8b949e",
        )
        self.gmail_status_lbl.pack(side="right")

        ctk.CTkLabel(
            gmail_card,
            text="Connect your Gmail account to ask Jarvis: 'Check my Gmail', 'Any unread emails?', or 'Read my emails' hands-free.",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        g_inputs = ctk.CTkFrame(gmail_card, fg_color="transparent")
        g_inputs.pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(g_inputs, text="Gmail Address:", width=130, anchor="w", font=ctk.CTkFont(size=12)).grid(row=0, column=0, pady=4, sticky="w")
        self.gmail_email_entry = ctk.CTkEntry(g_inputs, width=320, placeholder_text="yourname@gmail.com")
        self.gmail_email_entry.grid(row=0, column=1, padx=8, pady=4, sticky="w")
        if config.gmail_address:
            self.gmail_email_entry.insert(0, config.gmail_address)

        ctk.CTkLabel(g_inputs, text="App Password:", width=130, anchor="w", font=ctk.CTkFont(size=12)).grid(row=1, column=0, pady=4, sticky="w")
        self.gmail_pwd_entry = ctk.CTkEntry(g_inputs, width=320, show="*", placeholder_text="16-character Google App Password")
        self.gmail_pwd_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        if config.gmail_app_password:
            self.gmail_pwd_entry.insert(0, config.gmail_app_password)

        ctk.CTkLabel(
            gmail_card,
            text="💡 Tip: Create a 16-letter App Password at https://myaccount.google.com/apppasswords (select App: Other -> 'Jarvis').",
            font=ctk.CTkFont(size=11),
            text_color="#a5d6ff",
        ).pack(anchor="w", padx=16, pady=(4, 8))

        g_btns = ctk.CTkFrame(gmail_card, fg_color="transparent")
        g_btns.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            g_btns,
            text="🔍 Test Connection & Fetch Unread",
            width=210,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_test_gmail,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            g_btns,
            text="🌐 Open Web Gmail",
            width=140,
            height=30,
            fg_color="#21262d",
            command=lambda: self.worker.start_task("open gmail"),
        ).pack(side="left")

        # ── 3. GOOGLE CALENDAR INTEGRATION CARD ──────────────────
        cal_card = ctk.CTkFrame(self.view_settings, fg_color=_CARD_BG, corner_radius=12)
        cal_card.pack(fill="x", padx=16, pady=6)

        cal_head = ctk.CTkFrame(cal_card, fg_color="transparent")
        cal_head.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            cal_head,
            text="📅 Calendar Integration",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#80d8ff",
        ).pack(side="left")

        ctk.CTkLabel(
            cal_card,
            text="Ask Jarvis: 'What is on my schedule today?', 'Any meetings today?', or 'Schedule meeting with Alex at 3pm'.",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        c_inputs = ctk.CTkFrame(cal_card, fg_color="transparent")
        c_inputs.pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(c_inputs, text="Calendar Type:", width=130, anchor="w", font=ctk.CTkFont(size=12)).grid(row=0, column=0, pady=4, sticky="w")
        self.cal_pref_opt = ctk.CTkOptionMenu(
            c_inputs,
            values=["Google Calendar", "Windows Calendar"],
            width=220,
        )
        self.cal_pref_opt.grid(row=0, column=1, padx=8, pady=4, sticky="w")
        self.cal_pref_opt.set(config.calendar_preference or "Google Calendar")

        ctk.CTkLabel(c_inputs, text="Secret iCal URL:", width=130, anchor="w", font=ctk.CTkFont(size=12)).grid(row=1, column=0, pady=4, sticky="w")
        self.cal_ical_entry = ctk.CTkEntry(c_inputs, width=420, placeholder_text="https://calendar.google.com/calendar/ical/.../basic.ics")
        self.cal_ical_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        if config.calendar_ical_url:
            self.cal_ical_entry.insert(0, config.calendar_ical_url)

        ctk.CTkLabel(
            cal_card,
            text="💡 Tip: In Google Calendar -> Settings -> Click calendar -> 'Secret address in iCal format' to read events hands-free.",
            font=ctk.CTkFont(size=11),
            text_color="#a5d6ff",
        ).pack(anchor="w", padx=16, pady=(4, 8))

        c_btns = ctk.CTkFrame(cal_card, fg_color="transparent")
        c_btns.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(
            c_btns,
            text="📋 Check Today's Schedule",
            width=180,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_check_calendar,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            c_btns,
            text="🌐 Open Calendar",
            width=140,
            height=30,
            fg_color="#21262d",
            command=lambda: self.worker.start_task("open calendar"),
        ).pack(side="left")

        # ── 4. WHATSAPP INTEGRATION CARD ─────────────────────────
        wa_card = ctk.CTkFrame(self.view_settings, fg_color=_CARD_BG, corner_radius=12)
        wa_card.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(
            wa_card,
            text="💬 WhatsApp Integration",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#80d8ff",
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            wa_card,
            text="Ask Jarvis: 'Open WhatsApp', 'Any updates on WhatsApp?', or 'Send WhatsApp message to +12345 saying hello'.",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        w_inputs = ctk.CTkFrame(wa_card, fg_color="transparent")
        w_inputs.pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(w_inputs, text="Client Type:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=0, column=0, pady=4, sticky="w")
        self.wa_client_opt = ctk.CTkOptionMenu(
            w_inputs,
            values=["WhatsApp Web", "WhatsApp Desktop App"],
            width=220,
        )
        self.wa_client_opt.grid(row=0, column=1, padx=8, pady=4, sticky="w")
        self.wa_client_opt.set(config.whatsapp_client_type or "WhatsApp Web")

        ctk.CTkLabel(w_inputs, text="Default Phone Number:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=1, column=0, pady=4, sticky="w")
        self.wa_phone_entry = ctk.CTkEntry(w_inputs, width=280, placeholder_text="+1234567890 (optional)")
        self.wa_phone_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        if config.whatsapp_default_phone:
            self.wa_phone_entry.insert(0, config.whatsapp_default_phone)

        w_btns = ctk.CTkFrame(wa_card, fg_color="transparent")
        w_btns.pack(fill="x", padx=16, pady=(6, 14))

        ctk.CTkButton(
            w_btns,
            text="💬 Open WhatsApp",
            width=160,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.worker.start_task("open whatsapp"),
        ).pack(side="left")

        # ── 4b. GEMINI LIVE & AI PROVIDER SETTINGS ───────────────
        live_card = ctk.CTkFrame(self.view_settings, fg_color=_CARD_BG, corner_radius=12)
        live_card.pack(fill="x", padx=16, pady=6)

        l_head = ctk.CTkFrame(live_card, fg_color="transparent")
        l_head.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            l_head,
            text="⚡ Gemini Live Voice & Vision Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=_ACCENT_CYAN,
        ).pack(side="left")

        ctk.CTkButton(
            l_head,
            text="⚡ Launch Live Floating HUD",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=26,
            fg_color="#006699",
            hover_color="#0088cc",
            command=self.open_live_panel,
        ).pack(side="right")

        ctk.CTkLabel(
            live_card,
            text="Gemini Live enables natural continuous voice conversations, automatic screen viewing, and real-time interruption.",
            font=ctk.CTkFont(size=12),
            text_color="#8b949e",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        l_inputs = ctk.CTkFrame(live_card, fg_color="transparent")
        l_inputs.pack(fill="x", padx=16, pady=4)

        # AI Provider choice
        ctk.CTkLabel(l_inputs, text="Primary AI Provider:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=0, column=0, pady=4, sticky="w")
        self.ai_provider_opt = ctk.CTkOptionMenu(
            l_inputs,
            values=["Gemini Live (Voice + Vision)", "Gemini Cloud (Standard)", "Ollama (Local Offline)"],
            width=260,
        )
        self.ai_provider_opt.grid(row=0, column=1, padx=8, pady=4, sticky="w")
        if "live" in (config.ai_provider or "").lower():
            self.ai_provider_opt.set("Gemini Live (Voice + Vision)")
        elif "ollama" in (config.ai_provider or "").lower():
            self.ai_provider_opt.set("Ollama (Local Offline)")
        else:
            self.ai_provider_opt.set("Gemini Cloud (Standard)")

        # Live Model
        ctk.CTkLabel(l_inputs, text="Live Model Name:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=1, column=0, pady=4, sticky="w")
        self.live_model_entry = ctk.CTkEntry(l_inputs, width=260)
        self.live_model_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        self.live_model_entry.insert(0, getattr(config, "gemini_live_model", "gemini-2.0-flash-live-001"))

        # Voice selection
        ctk.CTkLabel(l_inputs, text="Live Spoken Voice:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=2, column=0, pady=4, sticky="w")
        self.live_voice_opt = ctk.CTkOptionMenu(
            l_inputs,
            values=["Puck", "Charon", "Kore", "Fenrir", "Aoede"],
            width=260,
        )
        self.live_voice_opt.grid(row=2, column=1, padx=8, pady=4, sticky="w")
        self.live_voice_opt.set(getattr(config, "live_voice", "Puck"))

        # Language code
        ctk.CTkLabel(l_inputs, text="Language Code:", width=140, anchor="w", font=ctk.CTkFont(size=12)).grid(row=3, column=0, pady=4, sticky="w")
        self.live_lang_entry = ctk.CTkEntry(l_inputs, width=120)
        self.live_lang_entry.grid(row=3, column=1, padx=8, pady=4, sticky="w")
        self.live_lang_entry.insert(0, getattr(config, "live_language", "en"))

        # Switches row
        l_sw_row = ctk.CTkFrame(live_card, fg_color="transparent")
        l_sw_row.pack(fill="x", padx=16, pady=4)

        self.sw_live_screen = ctk.CTkSwitch(
            l_sw_row,
            text="Share screen by default when Live session connects",
            font=ctk.CTkFont(size=12),
        )
        self.sw_live_screen.pack(side="left", padx=(0, 20))
        if getattr(config, "live_screen_share", False):
            self.sw_live_screen.select()
        else:
            self.sw_live_screen.deselect()

        # Push to talk info
        ctk.CTkLabel(
            live_card,
            text="🎙️ Push-to-Talk Hotkey: Ctrl+Space (Global across all Windows apps) • Red Stop: Ctrl+Alt+Q",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
        ).pack(anchor="w", padx=16, pady=(4, 4))

        # Free tier privacy notice
        ctk.CTkLabel(
            live_card,
            text="ℹ️ Google Privacy Notice: On the free tier, Google may use your data to improve its products.",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#94a3b8",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # ── 5. SAVE BUTTON & FEEDBACK ─────────────────────────────
        save_box = ctk.CTkFrame(self.view_settings, fg_color="transparent")
        save_box.pack(fill="x", padx=16, pady=(14, 20))

        self.btn_save_settings = ctk.CTkButton(
            save_box,
            text="💾 SAVE ALL SETTINGS & ACCOUNTS",
            height=40,
            width=280,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#238636",
            hover_color="#2ea043",
            command=self.save_all_settings,
        )
        self.btn_save_settings.pack(side="left", padx=(0, 16))

        self.save_feedback_lbl = ctk.CTkLabel(
            save_box,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=_ACCENT_GREEN,
        )
        self.save_feedback_lbl.pack(side="left")

    def _on_test_gmail(self) -> None:
        """Saves current credentials and tests Gmail IMAP connection."""
        self.save_all_settings()
        self.gmail_status_lbl.configure(text="● Connecting...", text_color=_ACCENT_GOLD)
        def _task():
            res = self.worker.check_gmail_inbox(max_results=3)
            if "Authentication Failed" in res or "Could not" in res:
                self.after(0, lambda: self.gmail_status_lbl.configure(text="❌ Auth Error", text_color=_ACCENT_RED))
            else:
                self.after(0, lambda: self.gmail_status_lbl.configure(text="● Connected", text_color=_ACCENT_GREEN))
            self.after(0, lambda: self.add_chat_message("Jarvis", res))
        threading.Thread(target=_task, daemon=True).start()

    def _on_check_calendar(self) -> None:
        """Checks schedule and reports in chat."""
        self.save_all_settings()
        def _task():
            res = self.worker.check_calendar_schedule()
            self.after(0, lambda: self.add_chat_message("Jarvis", res))
        threading.Thread(target=_task, daemon=True).start()

    def save_all_settings(self) -> None:
        """Persists all inputs into config and saves to jarvis_settings.json."""
        config.full_pc_control = bool(self.sw_full_control.get())
        config.voice_enabled = bool(self.sw_voice.get())
        config.gmail_address = self.gmail_email_entry.get().strip()
        config.gmail_app_password = self.gmail_pwd_entry.get().strip()
        config.calendar_preference = self.cal_pref_opt.get()
        config.calendar_ical_url = self.cal_ical_entry.get().strip()
        config.whatsapp_client_type = self.wa_client_opt.get()
        config.whatsapp_default_phone = self.wa_phone_entry.get().strip()
        config.ai_provider = self.ai_provider_opt.get()
        config.gemini_live_model = self.live_model_entry.get().strip() or "gemini-2.0-flash-live-001"
        config.live_voice = self.live_voice_opt.get()
        config.live_language = self.live_lang_entry.get().strip() or "en"
        config.live_screen_share = bool(self.sw_live_screen.get())
        config.save()

        # Update badge
        if config.gmail_address and config.gmail_app_password:
            self.gmail_status_lbl.configure(text="● Attached", text_color=_ACCENT_GREEN)
        else:
            self.gmail_status_lbl.configure(text="○ Not Attached", text_color="#8b949e")

        self.save_feedback_lbl.configure(text="✅ All settings saved successfully!", text_color=_ACCENT_GREEN)
        self.after(3000, lambda: self.save_feedback_lbl.configure(text=""))

    # ─────────────────────────────────────────────────────────────
    #  MODE SWITCHING LOGIC
    # ─────────────────────────────────────────────────────────────
    def switch_mode(self, mode: str) -> None:
        """Switch between the 4 clearly separated modes."""
        self.current_mode = mode

        # Hide all views
        self.view_voice.pack_forget()
        self.view_chat.pack_forget()
        self.view_screen.pack_forget()
        self.view_settings.pack_forget()

        # Reset button styles to minimal transparent pill
        self.btn_mode_voice.configure(fg_color="transparent", text_color="#94a3b8")
        self.btn_mode_chat.configure(fg_color="transparent", text_color="#94a3b8")
        self.btn_mode_screen.configure(fg_color="transparent", text_color="#94a3b8")
        self.btn_mode_settings.configure(fg_color="transparent", text_color="#94a3b8")

        if mode == "voice":
            self.view_voice.pack(fill="both", expand=True)
            self.btn_mode_voice.configure(fg_color=_ACCENT_CYAN, text_color="#05070a")
        elif mode == "chat":
            self.view_chat.pack(fill="both", expand=True)
            self.btn_mode_chat.configure(fg_color=_ACCENT_CYAN, text_color="#05070a")
        elif mode == "screen":
            self.view_screen.pack(fill="both", expand=True)
            self.btn_mode_screen.configure(fg_color=_ACCENT_CYAN, text_color="#05070a")
            # Automatically capture and inspect active screen immediately
            self.after(60, self.worker.describe_current_screen)
        elif mode == "settings":
            self.view_settings.pack(fill="both", expand=True)
            self.btn_mode_settings.configure(fg_color=_ACCENT_CYAN, text_color="#05070a")

    def open_live_panel(self) -> None:
        """Opens or brings to front the Gemini Live floating HUD panel."""
        if self.live_panel is not None and self.live_panel.winfo_exists():
            self.live_panel.lift()
            self.live_panel.focus_force()
            return
        self.worker.is_live_mode_active = True
        self.live_panel = GeminiLivePanel(self, self.live_engine)
        self.live_engine.start()

    def on_live_panel_closed(self) -> None:
        """Called when Gemini Live floating HUD is closed."""
        self.worker.is_live_mode_active = False

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
            self.voice_user_text.configure(text=f"You: {text.strip().rstrip('.')}")
        else:
            self.voice_jarvis_text.configure(text=f"Jarvis: {text.strip().rstrip('.')}")

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
            clean_title = window_title.strip().rstrip(".")
            self.screen_win_lbl.configure(text=f"Active: {clean_title[:60]}")
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

    def _on_space_press(self, event=None) -> None:
        """Invoked when user presses and holds Spacebar (or clicks & holds mic button)."""
        try:
            focus_w = self.focus_get()
            if focus_w:
                w_type = str(type(focus_w)).lower()
                if "entry" in w_type or "text" in w_type or focus_w == getattr(self, "text_input", None):
                    return
        except Exception:
            pass

        if self._space_is_held:
            return  # Prevent keyboard auto-repeat

        self._space_is_held = True
        self.voice_action_btn.configure(
            text="🔴 RECORDING (RELEASE SPACEBAR TO SEND)",
            fg_color="#3b0716",
            border_color="#f43f5e",
            text_color="#f43f5e"
        )
        self.logo_canvas.set_state("Listening")
        self.status_lbl.configure(text="Listening")
        self.status_dot.configure(text_color=_ACCENT_MAGENTA)
        self.worker.start_push_to_talk()

    def _on_space_release(self, event=None) -> None:
        """Invoked when user releases Spacebar (or mouse button)."""
        try:
            focus_w = self.focus_get()
            if focus_w:
                w_type = str(type(focus_w)).lower()
                if "entry" in w_type or "text" in w_type or focus_w == getattr(self, "text_input", None):
                    return
        except Exception:
            pass

        if not self._space_is_held:
            return

        self._space_is_held = False
        self.voice_action_btn.configure(
            text="🎙️ PRESS & HOLD SPACEBAR TO SPEAK",
            fg_color="#0a192f",
            border_color="#00f0ff",
            text_color="#00f0ff"
        )
        self.worker.stop_push_to_talk()

    def on_activate_window(self) -> None:
        """Brings Jarvis window to front when triggered by global shortcut."""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            if not config.always_on_top:
                self.after(500, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    def on_voice_talk_clicked(self) -> None:
        """Triggered from Talking Mode center button."""
        def _on_heard(spoken: str):
            self.after(0, lambda: self.worker.start_task(spoken))

        self.worker.record_voice(_on_heard)

    def on_emergency_stop_clicked(self) -> None:
        self.worker.stop()
        if hasattr(self, "live_engine"):
            self.live_engine.stop()
        if hasattr(self, "live_panel") and self.live_panel and self.live_panel.winfo_exists():
            self.live_panel.emergency_stop()
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
    parser.add_argument("--mode", choices=["voice", "chat", "screen", "settings"], default="voice")
    args = parser.parse_args()

    app = JarvisApp(start_mode=args.mode)
    app.mainloop()


if __name__ == "__main__":
    main()
