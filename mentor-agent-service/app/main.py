from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Mentor Agent Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    return application


app = create_app()
