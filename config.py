"""
config.py — Configuration management and persistence for Jarvis Desktop App.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass


def _get_config_path() -> str:
    # 1. Persistent home folder (~/.openjarvis/jarvis_settings.json)
    home_cfg = os.path.expanduser("~/.openjarvis/jarvis_settings.json")
    if os.path.exists(home_cfg):
        return home_cfg
    # 2. Next to executable
    if getattr(sys, "frozen", False):
        exe_cfg = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "jarvis_settings.json")
        if os.path.exists(exe_cfg):
            return exe_cfg
    # 3. Source directory
    src_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_settings.json")
    if os.path.exists(src_cfg):
        return src_cfg
    # Default fallback path
    os.makedirs(os.path.dirname(home_cfg), exist_ok=True)
    return home_cfg


_CONFIG_PATH = _get_config_path()


@dataclass
class JarvisConfig:
    ai_provider: str = "Gemini Cloud (with Ollama Fallback)"
    gemini_api_key: str = "AQ.Ab8RN6KQkLoVJNZMGLAPhEHftV-MmW-NE94xPxBHXZccwcuGIA"
    gemini_model: str = "gemini-3.1-flash-lite"
    use_gemini_cloud: bool = True
    ollama_host: str = "http://localhost:11434"
    model_name: str = "phi3:mini"
    vision_model: str = "moondream"
    timeout_seconds: int = 120
    keep_alive: str = "15m"
    voice_enabled: bool = True
    dry_run: bool = False
    ask_before_every_action: bool = False
    full_pc_control: bool = True
    always_on_top: bool = False
    max_steps: int = 5
    gmail_address: str = ""
    gmail_app_password: str = ""
    whatsapp_default_phone: str = ""
    whatsapp_client_type: str = "WhatsApp Web"
    calendar_preference: str = "Google Calendar"
    calendar_ical_url: str = ""

    @classmethod
    def load(cls) -> "JarvisConfig":
        if os.path.exists(_CONFIG_PATH):
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        target_path = _get_config_path()
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")


# Global config singleton
config = JarvisConfig.load()
