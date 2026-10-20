from __future__ import annotations

# pyrefly: ignore[missing-import]
import redis
from fastapi import Depends
from pymongo.database import Database

from app.database import get_mongo_db, get_redis_client
from app.repositories import (
    EventRepository,
    OrderRepository,
    RedisRepository,
    UserRepository,
)
from app.services import (
    EventService,
    OrderService,
    ReportService,
    ReservationService,
)


def get_db() -> Database:
    return get_mongo_db()


def get_redis() -> redis.Redis:
    return get_redis_client()


def get_user_repository(db: Database = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_event_repository(db: Database = Depends(get_db)) -> EventRepository:
    return EventRepository(db)


def get_order_repository(db: Database = Depends(get_db)) -> OrderRepository:
    return OrderRepository(db)


def get_redis_repository(client: redis.Redis = Depends(get_redis)) -> RedisRepository:
    return RedisRepository(client)


def get_event_service(
    event_repo: EventRepository = Depends(get_event_repository),
    redis_repo: RedisRepository = Depends(get_redis_repository),
) -> EventService:
    return EventService(event_repo=event_repo, redis_repo=redis_repo)


def get_reservation_service(
    user_repo: UserRepository = Depends(get_user_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    redis_repo: RedisRepository = Depends(get_redis_repository),
) -> ReservationService:
    return ReservationService(user_repo=user_repo, event_repo=event_repo, redis_repo=redis_repo)


def get_order_service(
    order_repo: OrderRepository = Depends(get_order_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    redis_repo: RedisRepository = Depends(get_redis_repository),
) -> OrderService:
    return OrderService(order_repo=order_repo, event_repo=event_repo, redis_repo=redis_repo)


def get_report_service(
    order_repo: OrderRepository = Depends(get_order_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    redis_repo: RedisRepository = Depends(get_redis_repository),
) -> ReportService:
    return ReportService(order_repo=order_repo, event_repo=event_repo, redis_repo=redis_repo)
