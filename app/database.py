from __future__ import annotations

import logging
import time
from typing import Optional

# pyrefly: ignore[missing-import]
import redis
from pymongo import MongoClient
from pymongo.database import Database

from app.config import settings

logger = logging.getLogger("ticketflash.database")

_mongo_client: Optional[MongoClient] = None
_redis_client: Optional[redis.Redis] = None


def create_indexes(database: Database) -> None:
    """Cria os índices obrigatórios no MongoDB conforme Requisito 3."""
    database["usuarios"].create_index("email", unique=True)
    database["eventos"].create_index([("categoria", 1), ("data", 1)])
    database["pedidos"].create_index("usuarioId")


def init_db(max_retries: int = 30, retry_delay: float = 1.0) -> tuple[MongoClient, redis.Redis]:
    """Inicializa conexões com MongoDB e Redis aguardando os serviços estarem prontos."""
    global _mongo_client, _redis_client

    mongo_client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=3000)
    redis_client = redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
    )

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            mongo_client.admin.command("ping")
            redis_client.ping()
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            if attempt == max_retries - 1:
                break
            time.sleep(retry_delay)

    if last_error is not None:
        mongo_client.close()
        redis_client.close()
        raise RuntimeError("MongoDB ou Redis não ficou disponível a tempo") from last_error

    db = mongo_client[settings.MONGO_DB]
    create_indexes(db)

    _mongo_client = mongo_client
    _redis_client = redis_client
    return mongo_client, redis_client


def close_db() -> None:
    """Encerra as conexões abertas com MongoDB e Redis."""
    global _mongo_client, _redis_client
    if _mongo_client:
        _mongo_client.close()
        _mongo_client = None
    if _redis_client:
        _redis_client.close()
        _redis_client = None


def get_mongo_db() -> Database:
    """Retorna a instância da base de dados do MongoDB."""
    if _mongo_client is None:
        raise RuntimeError("Conexão com MongoDB não inicializada")
    return _mongo_client[settings.MONGO_DB]


def get_redis_client() -> redis.Redis:
    """Retorna o cliente Redis conectado."""
    if _redis_client is None:
        raise RuntimeError("Conexão com Redis não inicializada")
    return _redis_client
