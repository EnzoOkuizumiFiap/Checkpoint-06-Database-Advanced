from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel


class ReservationModel(ApiModel):
    usuarioId: str = Field(description="ObjectId do usuário")
    eventoId: str = Field(description="ObjectId do evento")
    setor: str = Field(min_length=1, description="Nome do setor desejado")
    quantidade: int = Field(default=1, gt=0, description="Quantidade de ingressos a reservar")


class ReservationResponse(ApiModel):
    reservaId: str
    usuarioId: str
    eventoId: str
    setor: str
    quantidade: int
    ttlSegundos: int
