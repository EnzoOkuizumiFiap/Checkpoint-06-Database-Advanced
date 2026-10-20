from __future__ import annotations

import json
import logging
from typing import Any, Optional

# pyrefly: ignore[missing-import]
import redis

from app.config import settings

logger = logging.getLogger("ticketflash.redis_repository")

RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisRepository:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    # Cache de Eventos (Requisitos 5 e 9)
    def get_event_cache(self, event_id: str) -> Optional[dict[str, Any]]:
        cached = self.client.get(f"evento:{event_id}")
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                return None
        return None

    def set_event_cache(self, event_id: str, data: dict[str, Any], ttl: int = settings.EVENT_CACHE_TTL) -> None:
        self.client.set(f"evento:{event_id}", json.dumps(data, ensure_ascii=False), ex=ttl)

    def invalidate_event_cache(self, event_id: str) -> None:
        self.client.delete(f"evento:{event_id}")

    # Ranking de Visualizações (Requisito 7)
    def increment_event_view(self, event_id: str) -> None:
        self.client.zincrby(settings.RANKING_KEY, 1, event_id)

    def get_top_ranking(self, top_n: int = 5) -> list[tuple[str, int]]:
        entries = self.client.zrevrange(settings.RANKING_KEY, 0, top_n - 1, withscores=True)
        return [(str(event_id), int(score)) for event_id, score in entries]

    # Limite de Requisições (Requisito 8)
    def check_rate_limit(
        self,
        user_id: str,
        limit: int = settings.RATE_LIMIT,
        window_seconds: int = settings.RATE_WINDOW_SECONDS,
    ) -> tuple[int, int]:
        counter_key = f"limite:{user_id}"
        request_count = int(self.client.eval(RATE_LIMIT_SCRIPT, 1, counter_key, window_seconds))
        ttl = self.client.ttl(counter_key)
        return request_count, max(ttl, 1)

    # Reservas Temporárias (Requisito 6)
    def create_reservation(
        self,
        reservation_id: str,
        data: dict[str, Any],
        ttl: int = settings.RESERVATION_TTL,
    ) -> bool:
        created = self.client.set(
            f"reserva:{reservation_id}",
            json.dumps(data, ensure_ascii=False),
            nx=True,
            ex=ttl,
        )
        return bool(created)

    def get_reservation(self, reservation_id: str) -> Optional[dict[str, Any]]:
        raw = self.client.get(f"reserva:{reservation_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def delete_reservation(self, reservation_id: str) -> bool:
        deleted = self.client.delete(f"reserva:{reservation_id}")
        return deleted > 0

    # Lock Distribuído
    def acquire_lock(self, lock_key: str, token: str, ttl: int = 60) -> bool:
        acquired = self.client.set(lock_key, token, nx=True, ex=ttl)
        return bool(acquired)

    def release_lock(self, lock_key: str, token: str) -> None:
        self.client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, token)

    # Pub/Sub (Bônus)
    def publish(self, channel: str, message: dict[str, Any]) -> None:
        try:
            self.client.publish(channel, json.dumps(message, ensure_ascii=False))
        except redis.RedisError:
            logger.exception("Falha ao publicar mensagem no canal %s", channel)
