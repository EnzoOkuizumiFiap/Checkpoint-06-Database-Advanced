from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException

from app.repositories.event_repository import EventRepository
from app.repositories.redis_repository import RedisRepository
from app.schemas.common import to_public_json, validate_object_id
from app.schemas.event import EventModel


class EventService:
    def __init__(self, event_repo: EventRepository, redis_repo: RedisRepository) -> None:
        self.event_repo = event_repo
        self.redis_repo = redis_repo

    def create_event(self, event: EventModel) -> dict[str, Any]:
        doc = event.model_dump(mode="python", by_alias=True, exclude_none=True)
        inserted_id = self.event_repo.create(doc)
        doc["_id"] = inserted_id
        return to_public_json(doc)

    def list_events(
        self,
        categoria: Optional[str] = None,
        cidade: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        events = self.event_repo.find_all(categoria=categoria, cidade=cidade)
        return [to_public_json(e) for e in events]

    def get_event_with_cache(self, event_id_str: str) -> dict[str, Any]:
        """Padrão Cache-aside com registro de ranking e indicador de origem."""
        event_oid = validate_object_id(event_id_str, "eventoId")
        event_id = str(event_oid)

        # 1. Consulta o Redis primeiro
        cached = self.redis_repo.get_event_cache(event_id)
        if cached:
            doc = cached
            origin = "cache"
        else:
            # 2. Se não estiver no Redis, busca no MongoDB
            doc = self.event_repo.find_by_id(event_oid)
            if doc is None:
                raise HTTPException(status_code=404, detail="Evento não encontrado")
            doc = to_public_json(doc)
            # Salva no Redis com TTL de 60 s
            self.redis_repo.set_event_cache(event_id, doc)
            origin = "banco"

        # 3. Incrementa o ranking no Redis a cada consulta
        self.redis_repo.increment_event_view(event_id)

        return {"evento": doc, "origem": origin}

    def update_event(self, event_id_str: str, event: EventModel) -> dict[str, Any]:
        """Atualiza no MongoDB e invalida a chave no Redis."""
        event_oid = validate_object_id(event_id_str, "eventoId")
        doc = event.model_dump(mode="python", by_alias=True, exclude_none=True)

        updated = self.event_repo.update(event_oid, doc)
        if not updated:
            raise HTTPException(status_code=404, detail="Evento não encontrado")

        # Invalida o cache no Redis
        self.redis_repo.invalidate_event_cache(str(event_oid))

        refreshed = self.event_repo.find_by_id(event_oid)
        return to_public_json(refreshed)

    def delete_event(self, event_id_str: str) -> None:
        """Remove do MongoDB e invalida a chave no Redis."""
        event_oid = validate_object_id(event_id_str, "eventoId")
        deleted = self.event_repo.delete(event_oid)
        if not deleted:
            raise HTTPException(status_code=404, detail="Evento não encontrado")

        # Invalida o cache no Redis
        self.redis_repo.invalidate_event_cache(str(event_oid))
