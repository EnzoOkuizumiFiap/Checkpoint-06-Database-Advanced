from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import get_event_service, get_report_service
from app.schemas.event import EventModel, EventOriginResponse
from app.schemas.report import RankingResponse
from app.services.event_service import EventService
from app.services.report_service import ReportService

router = APIRouter(prefix="/eventos", tags=["eventos"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Criar evento")
def create_event(
    event: EventModel,
    service: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    return service.create_event(event)


@router.get("", summary="Listar eventos com filtros opcionais")
def list_events(
    categoria: Optional[str] = None,
    cidade: Optional[str] = None,
    service: EventService = Depends(get_event_service),
) -> list[dict[str, Any]]:
    return service.list_events(categoria=categoria, cidade=cidade)


@router.get("/ranking", summary="Top 5 eventos mais consultados (Redis Sorted Set)")
def event_ranking(
    report_service: ReportService = Depends(get_report_service),
) -> dict[str, Any]:
    return report_service.get_event_ranking()


@router.get("/{evento_id}", summary="Consultar evento por ID (Cache-aside + Ranking)")
def get_event(
    evento_id: str,
    service: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    return service.get_event_with_cache(evento_id)


@router.put("/{evento_id}", summary="Atualizar evento e invalidar cache")
def update_event(
    evento_id: str,
    event: EventModel,
    service: EventService = Depends(get_event_service),
) -> dict[str, Any]:
    return service.update_event(evento_id, event)


@router.delete("/{evento_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover evento e invalidar cache")
def delete_event(
    evento_id: str,
    service: EventService = Depends(get_event_service),
) -> Response:
    service.delete_event(evento_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
