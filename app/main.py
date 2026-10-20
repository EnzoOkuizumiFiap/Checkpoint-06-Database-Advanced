from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import redis
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from app.database import create_indexes

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ticketflash")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ticketflash")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EVENT_CACHE_TTL = 60
RESERVATION_TTL = 600
RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 60
RANKING_KEY = "eventos:ranking"


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class LocalModel(ApiModel):
    cidade: str = Field(min_length=1)
    endereco: str = Field(alias="endereço", min_length=1)


class SectorModel(ApiModel):
    nome: str = Field(min_length=1)
    preco: float = Field(alias="preço", gt=0)
    capacidade: int = Field(gt=0)
    vendidos: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def sold_cannot_exceed_capacity(self) -> "SectorModel":
        if self.vendidos > self.capacidade:
            raise ValueError("vendidos não pode exceder capacidade")
        return self


class EventModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    nome: str = Field(min_length=1)
    categoria: str = Field(min_length=1)
    data: datetime
    local: LocalModel
    atracoes: list[str] = Field(alias="atrações")
    setores: list[SectorModel] = Field(min_length=1)


class ReservationModel(ApiModel):
    usuarioId: str
    eventoId: str
    setor: str = Field(min_length=1)
    quantidade: int = Field(default=1, gt=0)


class ConfirmationModel(ApiModel):
    reservaId: str


@asynccontextmanager
async def lifespan(application: FastAPI):
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
    try:
        last_error: Exception | None = None
        for attempt in range(30):
            try:
                client.admin.command("ping")
                redis_client.ping()
                last_error = None
                break
            except Exception as exc:  # services may still be becoming ready
                last_error = exc
                if attempt == 29:
                    break
                time.sleep(1)
        if last_error is not None:
            raise RuntimeError("MongoDB ou Redis não ficou disponível") from last_error
        database = client[MONGO_DB]
        create_indexes(database)
        application.state.mongo_client = client
        application.state.database = database
        application.state.redis = redis_client
        yield
    finally:
        client.close()
        redis_client.close()


app = FastAPI(
    title="TicketFlash API",
    description="API de ingressos com MongoDB e Redis, conforme o Checkpoint 3 da FIAP.",
    version="1.0.0",
    lifespan=lifespan,
)


def _object_id(value: str, label: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail=f"{label} inválido")
    return ObjectId(value)


def _public(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _event_document(event: EventModel) -> dict[str, Any]:
    return event.model_dump(mode="python", by_alias=True, exclude_none=True)


def _database(application: FastAPI):
    return application.state.database


def _redis(application: FastAPI):
    return application.state.redis


@app.get("/health", tags=["infraestrutura"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/eventos", status_code=status.HTTP_201_CREATED, tags=["eventos"])
def create_event(event: EventModel) -> dict[str, Any]:
    document = _event_document(event)
    document.pop("_id", None)
    result = _database(app)["eventos"].insert_one(document)
    document["_id"] = result.inserted_id
    return _public(document)


@app.get("/eventos", tags=["eventos"])
def list_events(
    categoria: str | None = None,
    cidade: str | None = None,
) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if categoria:
        query["categoria"] = categoria
    if cidade:
        query["local.cidade"] = cidade
    cursor = _database(app)["eventos"].find(query).sort("data", 1)
    return [_public(document) for document in cursor]


@app.get("/eventos/ranking", tags=["eventos"])
def event_ranking() -> dict[str, list[dict[str, Any]]]:
    redis_client = _redis(app)
    entries = redis_client.zrevrange(RANKING_KEY, 0, 4, withscores=True)
    return {
        "ranking": [
            {"eventoId": event_id, "visualizacoes": int(score)}
            for event_id, score in entries
        ]
    }


@app.get("/eventos/{evento_id}", tags=["eventos"])
def get_event(evento_id: str) -> dict[str, Any]:
    event_oid = _object_id(evento_id, "eventoId")
    cache_key = f"evento:{event_oid}"
    redis_client = _redis(app)
    cached = redis_client.get(cache_key)
    if cached:
        document = json.loads(cached)
        origin = "cache"
    else:
        document = _database(app)["eventos"].find_one({"_id": event_oid})
        if document is None:
            raise HTTPException(status_code=404, detail="Evento não encontrado")
        document = _public(document)
        redis_client.set(cache_key, json.dumps(document, ensure_ascii=False), ex=EVENT_CACHE_TTL)
        origin = "banco"
    redis_client.zincrby(RANKING_KEY, 1, str(event_oid))
    return {"evento": document, "origem": origin}


@app.put("/eventos/{evento_id}", tags=["eventos"])
def update_event(evento_id: str, event: EventModel) -> dict[str, Any]:
    event_oid = _object_id(evento_id, "eventoId")
    document = _event_document(event)
    document.pop("_id", None)
    result = _database(app)["eventos"].update_one({"_id": event_oid}, {"$set": document})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    _redis(app).delete(f"evento:{event_oid}")
    updated = _database(app)["eventos"].find_one({"_id": event_oid})
    return _public(updated)


@app.delete("/eventos/{evento_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["eventos"])
def delete_event(evento_id: str) -> Response:
    event_oid = _object_id(evento_id, "eventoId")
    result = _database(app)["eventos"].delete_one({"_id": event_oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    _redis(app).delete(f"evento:{event_oid}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/relatorios/faturamento", tags=["relatórios"])
def revenue_report() -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"status": "confirmado"}},
        {"$group": {"_id": "$eventoId", "faturamento": {"$sum": "$valorTotal"}}},
        {
            "$lookup": {
                "from": "eventos",
                "localField": "_id",
                "foreignField": "_id",
                "as": "evento",
            }
        },
        {"$unwind": "$evento"},
        {
            "$project": {
                "_id": 0,
                "eventoId": {"$toString": "$_id"},
                "nome": "$evento.nome",
                "faturamento": 1,
            }
        },
        {"$sort": {"faturamento": -1}},
    ]
    return [_public(row) for row in _database(app)["pedidos"].aggregate(pipeline)]


@app.get("/relatorios/ocupacao/{evento_id}", tags=["relatórios"])
def occupancy_report(evento_id: str) -> list[dict[str, Any]]:
    event_oid = _object_id(evento_id, "eventoId")
    pipeline = [
        {"$match": {"_id": event_oid}},
        {"$unwind": "$setores"},
        {
            "$project": {
                "_id": 0,
                "eventoId": {"$toString": "$_id"},
                "setor": "$setores.nome",
                "vendidos": "$setores.vendidos",
                "capacidade": "$setores.capacidade",
                "percentualVendido": {
                    "$cond": [
                        {"$gt": ["$setores.capacidade", 0]},
                        {
                            "$multiply": [
                                {"$divide": ["$setores.vendidos", "$setores.capacidade"]},
                                100,
                            ]
                        },
                        0,
                    ]
                },
            }
        },
    ]
    rows = list(_database(app)["eventos"].aggregate(pipeline))
    if not rows:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return [_public(row) for row in rows]


RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@app.post("/reservas", status_code=status.HTTP_201_CREATED, tags=["compras"])
def create_reservation(request: ReservationModel) -> dict[str, Any]:
    user_oid = _object_id(request.usuarioId, "usuarioId")
    event_oid = _object_id(request.eventoId, "eventoId")
    database = _database(app)
    redis_client = _redis(app)

    if database["usuarios"].find_one({"_id": user_oid}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    counter_key = f"limite:{user_oid}"
    request_count = int(redis_client.eval(RATE_LIMIT_SCRIPT, 1, counter_key, RATE_WINDOW_SECONDS))
    if request_count > RATE_LIMIT:
        remaining = redis_client.ttl(counter_key)
        raise HTTPException(
            status_code=429,
            detail="Limite de 10 reservas por minuto excedido",
            headers={"Retry-After": str(max(remaining, 1))},
        )

    event = database["eventos"].find_one(
        {"_id": event_oid},
        {"_id": 1, "setores": 1},
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    sector = next((item for item in event.get("setores", []) if item.get("nome") == request.setor), None)
    if sector is None:
        raise HTTPException(status_code=404, detail="Setor não encontrado")
    if sector.get("capacidade", 0) - sector.get("vendidos", 0) < request.quantidade:
        raise HTTPException(status_code=409, detail="Não há ingressos suficientes no setor")

    reservation_id = ObjectId()
    reservation = {
        "reservaId": str(reservation_id),
        "usuarioId": str(user_oid),
        "eventoId": str(event_oid),
        "setor": request.setor,
        "quantidade": request.quantidade,
    }
    created = redis_client.set(
        f"reserva:{reservation_id}",
        json.dumps(reservation, ensure_ascii=False),
        nx=True,
        ex=RESERVATION_TTL,
    )
    if not created:
        raise HTTPException(status_code=503, detail="Não foi possível criar a reserva")
    return {**reservation, "ttlSegundos": RESERVATION_TTL}


def _capacity_filter(event_oid: ObjectId, sector_name: str, quantity: int) -> dict[str, Any]:
    selected_sector = {
        "$arrayElemAt": [
            {
                "$filter": {
                    "input": "$setores",
                    "as": "sector",
                    "cond": {"$eq": ["$$sector.nome", sector_name]},
                }
            },
            0,
        ]
    }
    return {
        "_id": event_oid,
        "setores": {"$elemMatch": {"nome": sector_name}},
        "$expr": {
            "$let": {
                "vars": {"sector": selected_sector},
                "in": {
                    "$lte": [
                        {"$add": [{"$ifNull": ["$$sector.vendidos", 0]}, quantity]},
                        "$$sector.capacidade",
                    ]
                },
            }
        },
    }


@app.post("/pedidos/confirmar", tags=["compras"])
def confirm_order(request: ConfirmationModel) -> dict[str, Any]:
    reservation_oid = _object_id(request.reservaId, "reservaId")
    database = _database(app)
    redis_client = _redis(app)
    reservation_key = f"reserva:{reservation_oid}"
    lock_key = f"confirmacao:{reservation_oid}"
    lock_token = uuid4().hex

    if not redis_client.set(lock_key, lock_token, nx=True, ex=60):
        raise HTTPException(status_code=409, detail="Esta reserva já está sendo confirmada")

    try:
        existing_order = database["pedidos"].find_one({"_id": reservation_oid})
        if existing_order and existing_order.get("status") == "confirmado":
            redis_client.delete(reservation_key)
            return _public(existing_order)

        raw_reservation = redis_client.get(reservation_key)
        if raw_reservation is None:
            raise HTTPException(status_code=410, detail="Reserva expirada ou inexistente")
        reservation = json.loads(raw_reservation)
        user_oid = _object_id(reservation["usuarioId"], "usuarioId")
        event_oid = _object_id(reservation["eventoId"], "eventoId")
        quantity = int(reservation["quantidade"])
        sector_name = reservation["setor"]
        event = database["eventos"].find_one(
            {"_id": event_oid, "setores.nome": sector_name},
            {"setores.$": 1},
        )
        if event is None or not event.get("setores"):
            raise HTTPException(status_code=404, detail="Evento ou setor não encontrado")
        sector = event["setores"][0]
        total = round(float(sector["preço"]) * quantity, 2)
        order = {
            "_id": reservation_oid,
            "usuarioId": user_oid,
            "eventoId": event_oid,
            "setor": sector_name,
            "quantidade": quantity,
            "valorTotal": total,
            "status": "processando",
            "criadoEm": datetime.now(timezone.utc),
        }

        inserted = False
        inventory_updated = False
        try:
            database["pedidos"].insert_one(order)
            inserted = True
            inventory_result = database["eventos"].update_one(
                _capacity_filter(event_oid, sector_name, quantity),
                {"$inc": {"setores.$.vendidos": quantity}},
            )
            if inventory_result.matched_count == 0:
                database["pedidos"].delete_one({"_id": reservation_oid})
                raise HTTPException(status_code=409, detail="Capacidade do setor esgotada")
            inventory_updated = True
            confirmed = database["pedidos"].update_one(
                {"_id": reservation_oid, "status": "processando"},
                {"$set": {"status": "confirmado"}},
            )
            if confirmed.matched_count == 0:
                raise PyMongoError("Não foi possível concluir o pedido")
        except HTTPException:
            raise
        except Exception as exc:
            if inventory_updated:
                rollback = database["eventos"].update_one(
                    {
                        "_id": event_oid,
                        "setores": {"$elemMatch": {"nome": sector_name, "vendidos": {"$gte": quantity}}},
                    },
                    {"$inc": {"setores.$.vendidos": -quantity}},
                )
                if rollback.matched_count == 0:
                    logger.exception("Falha ao compensar incremento do setor %s", sector_name)
            if inserted:
                database["pedidos"].delete_one({"_id": reservation_oid})
            raise HTTPException(status_code=500, detail="Falha ao confirmar o pedido") from exc

        confirmed_order = database["pedidos"].find_one({"_id": reservation_oid})
        redis_client.delete(reservation_key)
        try:
            redis_client.publish(
                "pedidos:confirmados",
                json.dumps(_public(confirmed_order), ensure_ascii=False),
            )
        except redis.RedisError:
            logger.exception("Pedido confirmado, mas não foi possível publicar o evento")
        return _public(confirmed_order)
    finally:
        redis_client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key, lock_token)
