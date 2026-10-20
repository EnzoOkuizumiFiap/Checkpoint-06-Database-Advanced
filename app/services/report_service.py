from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.repositories.event_repository import EventRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.common import to_public_json, validate_object_id


class ReportService:
    def __init__(
        self,
        order_repo: OrderRepository,
        event_repo: EventRepository,
        redis_repo: RedisRepository,
    ) -> None:
        self.order_repo = order_repo
        self.event_repo = event_repo
        self.redis_repo = redis_repo

    def get_revenue_report(self) -> list[dict[str, Any]]:
        """Relatório de faturamento por evento via $lookup e agregação."""
        rows = self.order_repo.get_revenue_report()
        return [to_public_json(row) for row in rows]

    def get_occupancy_report(self, event_id_str: str) -> list[dict[str, Any]]:
        """Relatório de ocupação por setor via $unwind e cálculo no MongoDB."""
        event_oid = validate_object_id(event_id_str, "eventoId")
        rows = self.event_repo.get_occupancy_report(event_oid)
        if not rows:
            raise HTTPException(status_code=404, detail="Evento não encontrado")
        return [to_public_json(row) for row in rows]

    def get_event_ranking(self) -> dict[str, list[dict[str, Any]]]:
        """Top 5 eventos mais consultados no Redis (Sorted Set)."""
        entries = self.redis_repo.get_top_ranking(top_n=5)
        return {
            "ranking": [
                {"eventoId": event_id, "visualizacoes": score}
                for event_id, score in entries
            ]
        }
