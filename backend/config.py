import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


class Settings:
    # NVIDIA_* (build.nvidia.com) takes priority when set; LLM_* is the fallback.
    llm_api_key: str = os.getenv("NVIDIA_API_KEY") or os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("NVIDIA_BASE_URL") or os.getenv(
        "LLM_BASE_URL", "https://api.openai.com/v1"
    )
    llm_model: str = os.getenv("NVIDIA_MODEL") or os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_fallback_model: str = os.getenv("NVIDIA_FALLBACK_MODEL") or os.getenv(
        "LLM_FALLBACK_MODEL", ""
    )
    llm_timeout_seconds: float = float(
        os.getenv("NVIDIA_TIMEOUT_SECONDS") or os.getenv("LLM_TIMEOUT_SECONDS") or 60
    )

    database_path: str = os.getenv("DATABASE_PATH", "kile.db")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8000)

    proactive_quiet_start: int = _int("PROACTIVE_QUIET_START", 22)
    proactive_quiet_end: int = _int("PROACTIVE_QUIET_END", 8)
    proactive_cooldown_hours: int = _int("PROACTIVE_COOLDOWN_HOURS", 12)

    whatsapp_access_token: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    whatsapp_phone_id: str = os.getenv("WHATSAPP_PHONE_ID", "")
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    whatsapp_app_secret: str = os.getenv("WHATSAPP_APP_SECRET", "")
    whatsapp_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v25.0")
    message_channel: str = os.getenv("MESSAGE_CHANNEL", "log")

    recent_message_limit: int = 30
    memory_limit: int = 8

    # Humanized reply pacing (seconds) — Kile never replies instantly
    reply_delay_min: float = float(os.getenv("REPLY_DELAY_MIN", "3") or 3)
    reply_delay_max: float = float(os.getenv("REPLY_DELAY_MAX", "9") or 9)

    @property
    def db_file(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = ROOT_DIR / path
        return path


settings = Settings()
