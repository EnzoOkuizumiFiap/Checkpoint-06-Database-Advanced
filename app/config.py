from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB: str = os.getenv("MONGO_DB", "ticketflash")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    EVENT_CACHE_TTL: int = int(os.getenv("EVENT_CACHE_TTL", "60"))
    RESERVATION_TTL: int = int(os.getenv("RESERVATION_TTL", "600"))
    RATE_LIMIT: int = int(os.getenv("RATE_LIMIT", "10"))
    RATE_WINDOW_SECONDS: int = int(os.getenv("RATE_WINDOW_SECONDS", "60"))
    RANKING_KEY: str = os.getenv("RANKING_KEY", "eventos:ranking")
    PUBSUB_CHANNEL: str = os.getenv("PUBSUB_CHANNEL", "pedidos:confirmados")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
