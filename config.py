"""
config.py — Configuration management and persistence for Jarvis Desktop App.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis_settings.json")


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
    ask_before_every_action: bool = True
    always_on_top: bool = False
    max_steps: int = 15

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
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")


# Global config singleton
config = JarvisConfig.load()
