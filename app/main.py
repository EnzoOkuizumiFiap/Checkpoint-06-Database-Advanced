from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.database import close_db, init_db
from app.routers import (
    events_router,
    health_router,
    reports_router,
    reservations_router,
)

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger("ticketflash")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação conectando e encerrando o MongoDB e Redis."""
    logger.info("Inicializando conexões com MongoDB e Redis...")
    init_db()
    logger.info("Bancos de dados prontos e índices verificados com sucesso.")
    yield
    logger.info("Encerrando conexões com os bancos de dados...")
    close_db()


app = FastAPI(
    title="TicketFlash API",
    description="API REST de ingressos com MongoDB e Redis em Arquitetura em Camadas (FIAP 2TDSPG).",
    version="1.0.0",
    lifespan=lifespan,
)

# Inclusão dos roteadores por domínio
app.include_router(health_router)
app.include_router(events_router)
app.include_router(reservations_router)
app.include_router(reports_router)
