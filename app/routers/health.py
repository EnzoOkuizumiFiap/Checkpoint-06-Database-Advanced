from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["infraestrutura"])


@router.get("/health", summary="Health check da API")
def health() -> dict[str, str]:
    return {"status": "ok"}
