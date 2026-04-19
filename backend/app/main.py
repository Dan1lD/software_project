from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import async_session_factory, init_db
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.routers.learners import router as learners_router
from app.routers.memorization import router as memorization_router
from app.routers.recommendations import router as recommend_router
from app.routers.transcription import router as speech_router
from app.seed import seed_poems


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with async_session_factory() as session:
        await seed_poems(session)
    yield


settings = get_settings()
app = FastAPI(title="Poetry Conversational Recommender", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)

api = APIRouter(prefix="/api/v1")
api.include_router(chat_router)
api.include_router(learners_router)
api.include_router(recommend_router)
api.include_router(memorization_router)
api.include_router(speech_router)
app.include_router(api)
