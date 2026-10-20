from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class ConfirmationModel(ApiModel):
    reservaId: str = Field(description="Identificador da reserva temporária no Redis")


class OrderResponse(ApiModel):
    id: str = Field(alias="_id")
    usuarioId: str
    eventoId: str
    setor: str
    quantidade: int
    valorTotal: float
    status: str
    criadoEm: Any
