from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from app.config import settings
from app.repositories.event_repository import EventRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.common import to_public_json, validate_object_id
from app.schemas.order import ConfirmationModel

logger = logging.getLogger("ticketflash.order_service")


class OrderService:
    def __init__(
        self,
        order_repo: OrderRepository,
        event_repo: EventRepository,
        redis_repo: RedisRepository,
    ) -> None:
        self.order_repo = order_repo
        self.event_repo = event_repo
        self.redis_repo = redis_repo

    def confirm_order(self, request: ConfirmationModel) -> dict[str, Any]:
        reservation_oid = validate_object_id(request.reservaId, "reservaId")
        reservation_id = str(reservation_oid)

        lock_key = f"confirmacao:{reservation_id}"
        lock_token = uuid4().hex

        # Trava distribuída temporária para evitar concorrência dupla
        if not self.redis_repo.acquire_lock(lock_key, lock_token, ttl=60):
            raise HTTPException(status_code=409, detail="Esta reserva já está sendo confirmada")

        try:
            # Idempotência: verifica se o pedido já foi concluído anteriormente
            existing = self.order_repo.find_by_id(reservation_oid)
            if existing and existing.get("status") == "confirmado":
                self.redis_repo.delete_reservation(reservation_id)
                return to_public_json(existing)

            # 1. Verifica se a reserva ainda existe no Redis
            reservation = self.redis_repo.get_reservation(reservation_id)
            if reservation is None:
                raise HTTPException(status_code=410, detail="Reserva expirada ou inexistente")

            user_oid = validate_object_id(reservation["usuarioId"], "usuarioId")
            event_oid = validate_object_id(reservation["eventoId"], "eventoId")
            quantity = int(reservation["quantidade"])
            sector_name = reservation["setor"]

            # Obtém informações de preço do setor
            sector = self.event_repo.find_sector_by_name(event_oid, sector_name)
            if sector is None:
                raise HTTPException(status_code=404, detail="Evento ou setor não encontrado")

            total_price = round(float(sector["preço"]) * quantity, 2)

            order_data = {
                "_id": reservation_oid,
                "usuarioId": user_oid,
                "eventoId": event_oid,
                "setor": sector_name,
                "quantidade": quantity,
                "valorTotal": total_price,
                "status": "processando",
                "criadoEm": datetime.now(timezone.utc),
            }

            inserted = False
            inventory_updated = False
            try:
                # 2. Grava pedido preliminar no MongoDB
                self.order_repo.insert(order_data)
                inserted = True

                # 3. Incrementa vendidos atômica e condicionalmente com $inc (Req. 10)
                inventory_updated = self.event_repo.increment_sector_sold_atomic(
                    event_id=event_oid,
                    sector_name=sector_name,
                    quantity=quantity,
                )
                if not inventory_updated:
                    self.order_repo.delete(reservation_oid)
                    raise HTTPException(status_code=409, detail="Capacidade do setor esgotada")

                # 4. Atualiza status para confirmado
                status_updated = self.order_repo.update_status(
                    order_id=reservation_oid,
                    current_status="processando",
                    new_status="confirmado",
                )
                if not status_updated:
                    raise PyMongoError("Não foi possível concluir a transição do pedido")

            except HTTPException:
                raise
            except Exception as exc:
                # Compensação caso ocorra erro inesperado
                if inventory_updated:
                    rolled_back = self.event_repo.rollback_sector_sold(
                        event_id=event_oid,
                        sector_name=sector_name,
                        quantity=quantity,
                    )
                    if not rolled_back:
                        logger.exception("Falha ao compensar incremento do setor %s", sector_name)
                if inserted:
                    self.order_repo.delete(reservation_oid)
                raise HTTPException(status_code=500, detail="Falha ao confirmar o pedido") from exc

            # 5. Apaga a reserva temporária do Redis
            self.redis_repo.delete_reservation(reservation_id)

            confirmed_order = self.order_repo.find_by_id(reservation_oid)
            confirmed_public = to_public_json(confirmed_order)

            # 6. Bônus Pub/Sub: publica evento no canal pedidos:confirmados
            self.redis_repo.publish(settings.PUBSUB_CHANNEL, confirmed_public)

            return confirmed_public

        finally:
            self.redis_repo.release_lock(lock_key, lock_token)
