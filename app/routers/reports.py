from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.dependencies import get_report_service
from app.services.report_service import ReportService

router = APIRouter(prefix="/relatorios", tags=["relatórios"])


@router.get("/faturamento", summary="Relatório de faturamento por evento ($lookup)")
def revenue_report(
    service: ReportService = Depends(get_report_service),
) -> list[dict[str, Any]]:
    return service.get_revenue_report()


@router.get("/ocupacao/{evento_id}", summary="Relatório de ocupação por setor ($unwind)")
def occupancy_report(
    evento_id: str,
    service: ReportService = Depends(get_report_service),
) -> list[dict[str, Any]]:
    return service.get_occupancy_report(evento_id)
