"""
live_ui_panel.py — Gemini-Style Floating HUD Window for Real-Time Live Assistant.

Features:
  1. Compact floating glass panel with optional pin-on-top.
  2. Animated Glowing Orb visualizer changing with states (Listening, Thinking, Speaking, Idle).
  3. Live Screen Share Indicator with one-click Stop button.
  4. Real-time spoken transcript of both sides (You & Jarvis).
  5. Action approval confirmation banner.
  6. Push-to-Talk button (Mouse hold or Ctrl+Space).
  7. Instant Emergency STOP button (Ctrl+Alt+Q).
"""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, Callable, Optional

import customtkinter as ctk

from config import config

# Palette
_BG_DARK = "#05070a"
_HEADER_BG = "#080c14"
_CARD_BG = "#0c111c"
_CARD_BORDER = "#162032"
_ACCENT_CYAN = "#00f0ff"
_ACCENT_GREEN = "#10b981"
_ACCENT_RED = "#ef4444"
_ACCENT_GOLD = "#fbbf24"
_TEXT_MUTED = "#94a3b8"


class MiniGlowingOrb(ctk.CTkCanvas):
    """Compact fluid neon orb visualizer for the floating live panel."""

    def __init__(self, master, width=280, height=220, **kwargs):
        super().__init__(master, width=width, height=height, bg=_BG_DARK, highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.angle = 0.0
        self.state = "Idle"
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

        if self.state == "Listening":
            speed_mult = 1.6
            ribbon_amp = 14.0
            pulse = math.sin(self.angle * 4.0) * 6.0
            ribbon_color = "#00f0ff"
            glow_aura = "#083344"
            core_shades = ["#ff3366", "#ff2a5f", "#f43f5e", "#fb7185"]
        elif self.state == "Thinking":
            speed_mult = 2.4
            ribbon_amp = 11.0
            pulse = math.sin(self.angle * 6.0) * 5.0
            ribbon_color = "#38bdf8"
            glow_aura = "#0c4a6e"
            core_shades = ["#fbbf24", "#f59e0b", "#f43f5e", "#d97706"]
        elif self.state == "Speaking":
            speed_mult = 2.0
            ribbon_amp = 16.0
            pulse = math.sin(self.angle * 3.5) * 8.0
            ribbon_color = "#22d3ee"
            glow_aura = "#155e75"
            core_shades = ["#ff4d6d", "#f43f5e", "#e11d48", "#fb7185"]
        elif self.state == "Stopped":
            speed_mult = 0.2
            ribbon_amp = 4.0
            pulse = 0.0
            ribbon_color = "#ef4444"
            glow_aura = "#450a0a"
            core_shades = ["#7f1d1d", "#991b1b", "#b91c1c", "#ef4444"]
        else:  # Idle
            speed_mult = 1.0
            ribbon_amp = 8.0
            pulse = math.sin(self.angle * 1.5) * 3.0
            ribbon_color = "#00f0ff"
            glow_aura = "#041d2d"
            core_shades = ["#ff3366", "#ff4d6d", "#f43f5e", "#800f2f"]

        self.angle += 0.04 * speed_mult

        # Subtle backdrop glow
        r_aura = 90 + pulse * 0.5
        self.create_oval(cx - r_aura, cy - r_aura, cx + r_aura, cy + r_aura, fill=glow_aura, outline="")

        # Concentric orbital rings
        arc_cfgs = [
            (46, self.angle * 36, 120, core_shades[0], 1.4),
            (56, -self.angle * 44 + 40, 90, core_shades[1], 1.1),
            (66, self.angle * 28 + 100, 140, core_shades[2], 1.5),
            (76, -self.angle * 32 + 180, 80, core_shades[3], 1.0),
            (86, self.angle * 22 + 250, 150, core_shades[1], 1.2),
        ]
        for radius, start, extent, color, width in arc_cfgs:
            self.create_arc(
                cx - radius, cy - radius, cx + radius, cy + radius,
                start=start % 360, extent=extent,
                style="arc", outline=color, width=width
            )

        # Fluid undulating neon ribbon
        num_pts = 60
        cyan_pts = []
        base_r = 72 + pulse
        amp1 = ribbon_amp * math.sin(self.angle * 1.8)
        amp2 = (ribbon_amp * 0.6) * math.cos(self.angle * 2.3)

        for i in range(num_pts + 1):
            th = i * 2 * math.pi / num_pts
            r = base_r + amp1 * math.sin(3 * th + self.angle * 2) + amp2 * math.cos(2 * th - self.angle * 1.3)
            px = cx + r * math.cos(th)
            py = cy + r * math.sin(th)
            cyan_pts.extend([px, py])

        self.create_line(cyan_pts, smooth=True, fill="#042f40", width=9)
        self.create_line(cyan_pts, smooth=True, fill="#0891b2", width=5)
        self.create_line(cyan_pts, smooth=True, fill=ribbon_color, width=2.4)
        self.create_line(cyan_pts, smooth=True, fill="#f0fdfa", width=1.0)

        # Inner dark core void
        self.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill="#05070a", outline="#1c0a12", width=1.2)

        self.after(35, self._animate)


class GeminiLivePanel(ctk.CTkToplevel):
    """Floating Gemini Live HUD window."""

    def __init__(self, master: Any, engine: Any) -> None:
        super().__init__(master)
        self.engine = engine

        self.title("⚡ Jarvis — Gemini Live")
        self.geometry("450x580")
        self.minsize(400, 520)
        self.configure(fg_color=_BG_DARK)

        # Always on top by default for live floating experience
        self.attributes("-topmost", True)

        self._build_header()
        self._build_body()
        self._wire_engine_callbacks()

        # Handle window close cleanly
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_header(self) -> None:
        self.header = ctk.CTkFrame(self, height=48, fg_color=_HEADER_BG, corner_radius=0)
        self.header.pack(fill="x", side="top")

        # Live Badge
        logo_box = ctk.CTkFrame(self.header, fg_color="transparent")
        logo_box.pack(side="left", padx=(12, 4), pady=6)

        ctk.CTkLabel(
            logo_box, text="⚡", font=ctk.CTkFont(size=18, weight="bold"), text_color=_ACCENT_CYAN
        ).pack(side="left")

        self.status_pill = ctk.CTkLabel(
            logo_box,
            text="LIVE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=_ACCENT_GREEN,
            fg_color="#0d2818",
            corner_radius=6,
            padx=6,
            pady=2,
        )
        self.status_pill.pack(side="left", padx=6)

        # Screen Share Status Indicator & Stop Button
        self.screen_share_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        self.screen_share_frame.pack(side="left", padx=4)

        self.screen_indicator = ctk.CTkLabel(
            self.screen_share_frame,
            text="Sharing screen",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#38bdf8",
            fg_color="#082f49",
            corner_radius=6,
            padx=6,
            pady=2,
        )

        self.btn_stop_sharing = ctk.CTkButton(
            self.screen_share_frame,
            text="✖ Stop",
            font=ctk.CTkFont(size=10, weight="bold"),
            width=54,
            height=22,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            text_color="#fca5a5",
            corner_radius=6,
            command=self.toggle_screen_share,
        )

        # Emergency STOP button
        ctk.CTkButton(
            self.header,
            text="🚨 STOP",
            font=ctk.CTkFont(size=10, weight="bold"),
            width=62,
            height=26,
            fg_color="#3b0716",
            border_color=_ACCENT_RED,
            border_width=1,
            hover_color="#4c0519",
            text_color="#f87171",
            corner_radius=12,
            command=self.emergency_stop,
        ).pack(side="right", padx=(4, 12), pady=10)

        # Pin On Top Toggle
        self.pin_btn = ctk.CTkButton(
            self.header,
            text="📌",
            font=ctk.CTkFont(size=12),
            width=28,
            height=26,
            fg_color="#162032",
            hover_color="#233554",
            corner_radius=12,
            command=self.toggle_pin,
        )
        self.pin_btn.pack(side="right", padx=4)

    def _build_body(self) -> None:
        # 1. Mini Glowing Orb Visualizer
        self.orb_canvas = MiniGlowingOrb(self, width=280, height=190)
        self.orb_canvas.pack(pady=(6, 2))

        # Status text below orb
        self.state_label = ctk.CTkLabel(
            self,
            text="✨ STANDBY — TALK FREELY",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=_ACCENT_CYAN,
        )
        self.state_label.pack(pady=(0, 4))

        # 2. Confirmation Banner (hidden by default)
        self.confirm_frame = ctk.CTkFrame(self, fg_color="#24141e", border_color=_ACCENT_RED, border_width=1, corner_radius=10)
        self.confirm_label = ctk.CTkLabel(
            self.confirm_frame,
            text="Jarvis wants to execute an action. Approve?",
            font=ctk.CTkFont(size=11),
            text_color="#fca5a5",
            wraplength=380,
            justify="center",
        )
        self.confirm_label.pack(padx=10, pady=(6, 4))

        c_btns = ctk.CTkFrame(self.confirm_frame, fg_color="transparent")
        c_btns.pack(pady=(2, 6))

        ctk.CTkButton(
            c_btns, text="✔ Approve", width=88, height=24, fg_color="#15803d", hover_color="#16a34a",
            command=lambda: self._on_confirm_click(True)
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            c_btns, text="✖ Cancel", width=88, height=24, fg_color="#b91c1c", hover_color="#dc2626",
            command=lambda: self._on_confirm_click(False)
        ).pack(side="left", padx=4)

        # 3. Live Spoken Transcript Card
        self.transcript_card = ctk.CTkFrame(
            self, fg_color=_CARD_BG, border_color=_CARD_BORDER, border_width=1, corner_radius=12
        )
        self.transcript_card.pack(fill="x", padx=16, pady=6)

        self.transcript_user = ctk.CTkLabel(
            self.transcript_card,
            text="You: Speak or hold Ctrl+Space...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
            wraplength=390,
            justify="center",
        )
        self.transcript_user.pack(padx=10, pady=(8, 2))

        self.transcript_jarvis = ctk.CTkLabel(
            self.transcript_card,
            text="Jarvis: Standing by for your voice, sir.",
            font=ctk.CTkFont(size=12),
            text_color="#f1f5f9",
            wraplength=390,
            justify="center",
        )
        self.transcript_jarvis.pack(padx=10, pady=(2, 8))

        # 4. Controls: Push-To-Talk & Screen Share
        ctrl_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=16, pady=8)

        # Push to Talk Pill
        self.btn_ptt = ctk.CTkButton(
            ctrl_frame,
            text="🎙️ HOLD TO SPEAK (Ctrl+Space)",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=38,
            corner_radius=19,
            fg_color="#0a192f",
            border_color=_ACCENT_CYAN,
            border_width=1.5,
            text_color=_ACCENT_CYAN,
            hover_color="#102e4d",
        )
        self.btn_ptt.pack(fill="x", pady=4)

        # Bind mouse press and release
        self.btn_ptt.bind("<ButtonPress-1>", lambda e: self.engine.set_ptt(True))
        self.btn_ptt.bind("<ButtonRelease-1>", lambda e: self.engine.set_ptt(False))

        # Action Buttons Row
        row_btns = ctk.CTkFrame(ctrl_frame, fg_color="transparent")
        row_btns.pack(fill="x", pady=2)

        self.btn_screen_toggle = ctk.CTkButton(
            row_btns,
            text="🖥️ Share Screen",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=30,
            corner_radius=15,
            fg_color="#162032",
            hover_color="#1f2d47",
            command=self.toggle_screen_share,
        )
        self.btn_screen_toggle.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_mute_toggle = ctk.CTkButton(
            row_btns,
            text="🔊 Disconnect",
            font=ctk.CTkFont(size=11, weight="bold"),
            height=30,
            corner_radius=15,
            fg_color="#2b1118",
            text_color="#fca5a5",
            hover_color="#451220",
            command=self.on_close,
        )
        self.btn_mute_toggle.pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _wire_engine_callbacks(self) -> None:
        """Register listeners from the Live engine to update this UI."""
        self.engine.callbacks["on_status"] = self._thread_safe(self.on_status_changed)
        self.engine.callbacks["on_transcript"] = self._thread_safe(self.on_transcript_received)
        self.engine.callbacks["on_screen_share"] = self._thread_safe(self.on_screen_share_updated)
        self.engine.callbacks["on_confirm"] = self._thread_safe(self.on_confirm_requested)

    def _thread_safe(self, func: Callable) -> Callable:
        def _wrapper(*args, **kwargs):
            try:
                self.after(0, lambda: func(*args, **kwargs))
            except Exception:
                pass
        return _wrapper

    # ─────────────────────────────────────────────────────────────
    #  UI EVENT HANDLERS
    # ─────────────────────────────────────────────────────────────
    def on_status_changed(self, state: str) -> None:
        self.orb_canvas.set_state(state)
        label_text = f"✨ {state.upper()}"
        if state == "Listening":
            label_text = "🎙️ LISTENING..."
            self.state_label.configure(text=label_text, text_color=_ACCENT_CYAN)
        elif state == "Thinking":
            label_text = "🧠 PROCESSING..."
            self.state_label.configure(text=label_text, text_color=_ACCENT_GOLD)
        elif state == "Speaking":
            label_text = "🔊 SPEAKING..."
            self.state_label.configure(text=label_text, text_color="#38bdf8")
        elif state == "Acting":
            label_text = "⚡ PERFORMING ACTION..."
            self.state_label.configure(text=label_text, text_color=_ACCENT_GREEN)
        elif state == "Stopped":
            label_text = "🛑 STOPPED"
            self.state_label.configure(text=label_text, text_color=_ACCENT_RED)
        else:
            self.state_label.configure(text=label_text, text_color=_ACCENT_CYAN)

    def on_transcript_received(self, sender: str, text: str, is_final: bool = False) -> None:
        clean = text.strip()
        if not clean:
            return
        if sender == "You":
            self.transcript_user.configure(text=f"You: {clean}")
        else:
            self.transcript_jarvis.configure(text=f"Jarvis: {clean}")

    def on_screen_share_updated(self, active: bool) -> None:
        if active:
            self.screen_indicator.pack(side="left", padx=2)
            self.btn_stop_sharing.pack(side="left", padx=2)
            self.btn_screen_toggle.configure(text="🛑 Stop Sharing", fg_color="#3b0716", text_color="#fca5a5")
        else:
            self.screen_indicator.pack_forget()
            self.btn_stop_sharing.pack_forget()
            self.btn_screen_toggle.configure(text="🖥️ Share Screen", fg_color="#162032", text_color="#f1f5f9")

    def on_confirm_requested(self, prompt: str) -> None:
        self.confirm_label.configure(text=prompt)
        self.confirm_frame.pack(fill="x", padx=16, pady=4, after=self.state_label)

    def _on_confirm_click(self, approved: bool) -> None:
        self.confirm_frame.pack_forget()
        self.engine.approve_action(approved)

    def toggle_screen_share(self) -> None:
        new_state = not self.engine.screen_share_active
        self.engine.set_screen_share(new_state)

    def toggle_pin(self) -> None:
        current = bool(self.attributes("-topmost"))
        self.attributes("-topmost", not current)
        self.pin_btn.configure(fg_color="#00f0ff" if not current else "#162032", text_color="#000000" if not current else "#ffffff")

    def emergency_stop(self) -> None:
        self.engine.stop()
        self.confirm_frame.pack_forget()
        self.on_status_changed("Stopped")

    def on_close(self) -> None:
        self.engine.stop()
        self.destroy()
