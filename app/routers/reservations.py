from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status

from app.dependencies import get_order_service, get_reservation_service
from app.schemas.order import ConfirmationModel
from app.schemas.reservation import ReservationModel
from app.services.order_service import OrderService
from app.services.reservation_service import ReservationService

router = APIRouter(tags=["compras"])


@router.post("/reservas", status_code=status.HTTP_201_CREATED, summary="Criar reserva temporária no Redis")
def create_reservation(
    request: ReservationModel,
    service: ReservationService = Depends(get_reservation_service),
) -> dict[str, Any]:
    return service.create_reservation(request)


@router.post("/pedidos/confirmar", summary="Confirmar pedido com decremento atômico de vagas")
def confirm_order(
    request: ConfirmationModel,
    service: OrderService = Depends(get_order_service),
) -> dict[str, Any]:
    return service.confirm_order(request)
