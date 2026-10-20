from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.reports import router as reports_router
from app.routers.reservations import router as reservations_router

__all__ = [
    "events_router",
    "reservations_router",
    "reports_router",
    "health_router",
]
