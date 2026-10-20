from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import ApiModel


class LocalModel(ApiModel):
    cidade: str = Field(min_length=1, description="Cidade onde ocorrerá o evento")
    endereco: str = Field(alias="endereço", min_length=1, description="Endereço do evento")


class SectorModel(ApiModel):
    nome: str = Field(min_length=1, description="Nome do setor")
    preco: float = Field(alias="preço", gt=0, description="Preço do ingresso")
    capacidade: int = Field(gt=0, description="Capacidade total de ingressos")
    vendidos: int = Field(default=0, ge=0, description="Ingressos já vendidos")

    @model_validator(mode="after")
    def sold_cannot_exceed_capacity(self) -> "SectorModel":
        if self.vendidos > self.capacidade:
            raise ValueError("vendidos não pode exceder capacidade")
        return self


class EventModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    nome: str = Field(min_length=1, description="Nome do evento")
    categoria: str = Field(min_length=1, description="Categoria do evento")
    data: datetime = Field(description="Data e hora do evento")
    local: LocalModel = Field(description="Localização do evento")
    atracoes: list[str] = Field(alias="atrações", description="Lista de atrações")
    setores: list[SectorModel] = Field(min_length=1, description="Setores e ingressos disponíveis")


class EventOriginResponse(BaseModel):
    evento: dict[str, Any]
    origem: Literal["banco", "cache"]
