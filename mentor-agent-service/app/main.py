import logging
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.dependencies import verify_api_key
from app.routers import chat, health

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger("app").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Run Alembic migrations on startup (idempotent — already-applied revisions are skipped)
    try:
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        logger.info("Database migrations applied successfully")
    except Exception as exc:
        logger.error("Failed to run database migrations: %s", exc)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Mentor Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(chat.router, dependencies=[Depends(verify_api_key)])
    return application


app = create_app()
