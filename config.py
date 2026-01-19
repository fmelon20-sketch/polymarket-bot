"""Configuration module for the Polymarket Telegram Bot."""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Telegram settings
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # Polling settings
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "180"))
    )

    # API settings
    gamma_api_base_url: str = "https://gamma-api.polymarket.com"
    clob_api_base_url: str = "https://clob.polymarket.com"

    # Health check settings
    health_port: int = field(default_factory=lambda: int(os.getenv("PORT", "8080")))

    # Alert thresholds (customizable)
    volume_threshold_usd: float = field(
        default_factory=lambda: float(os.getenv("VOLUME_THRESHOLD_USD", "10000"))
    )
    price_change_threshold: float = field(
        default_factory=lambda: float(os.getenv("PRICE_CHANGE_THRESHOLD", "0.10"))
    )

    # Optional: filter by tags/categories
    watched_tags: Optional[list[str]] = field(
        default_factory=lambda: os.getenv("WATCHED_TAGS", "").split(",") if os.getenv("WATCHED_TAGS") else None
    )

    def validate(self) -> bool:
        """Validate that required configuration is present."""
        if not self.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
        if not self.telegram_chat_id:
            raise ValueError("TELEGRAM_CHAT_ID environment variable is required")
        return True


config = Config()
