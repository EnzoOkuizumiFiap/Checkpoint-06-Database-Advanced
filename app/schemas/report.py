from __future__ import annotations

from pydantic import BaseModel


class RevenueReportItem(BaseModel):
    eventoId: str
    nome: str
    faturamento: float


class OccupancyReportItem(BaseModel):
    eventoId: str
    setor: str
    vendidos: int
    capacidade: int
    percentualVendido: float


class RankingItem(BaseModel):
    eventoId: str
    visualizacoes: int


class RankingResponse(BaseModel):
    ranking: list[RankingItem]
