from __future__ import annotations

from typing import Any

from bson import ObjectId
from fastapi import HTTPException

from app.config import settings
from app.repositories.event_repository import EventRepository
from app.repositories.redis_repository import RedisRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import validate_object_id
from app.schemas.reservation import ReservationModel


class ReservationService:
    def __init__(
        self,
        user_repo: UserRepository,
        event_repo: EventRepository,
        redis_repo: RedisRepository,
    ) -> None:
        self.user_repo = user_repo
        self.event_repo = event_repo
        self.redis_repo = redis_repo

    def create_reservation(self, request: ReservationModel) -> dict[str, Any]:
        user_oid = validate_object_id(request.usuarioId, "usuarioId")
        event_oid = validate_object_id(request.eventoId, "eventoId")

        # 1. Valida existência do usuário no MongoDB
        if not self.user_repo.exists(user_oid):
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        # 2. Valida limite de requisições no Redis (Req. 8: 10 reservas por minuto)
        request_count, remaining_ttl = self.redis_repo.check_rate_limit(
            user_id=str(user_oid),
            limit=settings.RATE_LIMIT,
            window_seconds=settings.RATE_WINDOW_SECONDS,
        )
        if request_count > settings.RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Limite de {settings.RATE_LIMIT} reservas por minuto excedido",
                headers={"Retry-After": str(remaining_ttl)},
            )

        # 3. Confere no MongoDB se o evento e o setor existem e têm vagas
        event = self.event_repo.find_by_id_with_projection(event_oid, {"_id": 1, "setores": 1})
        if event is None:
            raise HTTPException(status_code=404, detail="Evento não encontrado")

        sector = next(
            (item for item in event.get("setores", []) if item.get("nome") == request.setor),
            None,
        )
        if sector is None:
            raise HTTPException(status_code=404, detail="Setor não encontrado")

        available_tickets = sector.get("capacidade", 0) - sector.get("vendidos", 0)
        if available_tickets < request.quantidade:
            raise HTTPException(status_code=409, detail="Não há ingressos suficientes no setor")

        # 4. Cria a reserva no Redis com SET NX EX e TTL de 600 segundos (Req. 6)
        reservation_id = ObjectId()
        reservation_data = {
            "reservaId": str(reservation_id),
            "usuarioId": str(user_oid),
            "eventoId": str(event_oid),
            "setor": request.setor,
            "quantidade": request.quantidade,
        }

        created = self.redis_repo.create_reservation(
            reservation_id=str(reservation_id),
            data=reservation_data,
            ttl=settings.RESERVATION_TTL,
        )
        if not created:
            raise HTTPException(status_code=503, detail="Não foi possível criar a reserva")

        return {**reservation_data, "ttlSegundos": settings.RESERVATION_TTL}
