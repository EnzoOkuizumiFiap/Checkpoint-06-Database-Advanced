from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def validate_object_id(value: str, label: str = "ID") -> ObjectId:
    """Valida e converte uma string para ObjectId do MongoDB."""
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail=f"{label} inválido")
    return ObjectId(value)


def to_public_json(value: Any) -> Any:
    """Serializa estruturas com ObjectId e datetime para tipos nativos JSON."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: to_public_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_public_json(item) for item in value]
    return value
