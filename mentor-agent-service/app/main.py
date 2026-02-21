import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

logging.getLogger("app").setLevel(logging.INFO)

from app.dependencies import verify_api_key
from app.routers import chat, health


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
    application.include_router(chat.router, dependencies=[Depends(verify_api_key)])
    return application


app = create_app()
