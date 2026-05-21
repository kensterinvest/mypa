"""Configuration loaded from /etc/mypa/env (or .env in dev).

Every secret, identity, and integration credential comes from env.
Nothing hardcoded — see the productization section of the master plan.
"""
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide config. Read once at startup."""

    model_config = SettingsConfigDict(
        env_file=os.environ.get("MYPA_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Identity (productization) ---
    public_host: str = Field(default="mypa.z-tidus.com")
    user_name: str = Field(default="user")
    tz: str = Field(default="Etc/UTC")
    locale: str = Field(default="en-GB")

    # --- Auth ---
    bearer_token_rw: str = Field(default="")  # required at boot; fail-fast in main
    bearer_token_ro: str = Field(default="")

    # --- Storage ---
    db_path: Path = Field(default=Path("/var/lib/mypa/mypa.db"))
    sqlcipher_key: str = Field(default="")
    # Windows dev escape hatch — plain SQLite when sqlcipher3-binary unavailable
    test_no_encryption: bool = Field(default=False)

    # --- Integrations (all optional) ---
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    telegram_auto_capture: bool = Field(default=False)

    anthropic_api_key: str = Field(default="")
    image_extraction_enabled: bool = Field(default=False)
    image_extract_daily_max: int = Field(default=50)

    google_client_id: str = Field(default="")
    google_client_secret: str = Field(default="")

    openai_api_key: str = Field(default="")  # for Whisper voice transcription
    whisper_monthly_max_min: int = Field(default=300)

    # --- Behavior flags ---
    implicit_location_capture: bool = Field(default=False)
    outcome_nudge_enabled: bool = Field(default=False)
    calendar_conflict_notes: bool = Field(default=True)

    # --- Logging ---
    audit_log_path: Path = Field(default=Path("/var/log/mypa-mcp.log"))
    blob_dir: Path = Field(default=Path("/var/lib/mypa/blobs"))


_settings: Settings | None = None


def settings() -> Settings:
    """Memoized singleton accessor."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
