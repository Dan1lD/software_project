from __future__ import annotations

import asyncio
from pathlib import Path

from app.database import Base
from app.models.tables import Poem, PoemLanguage
from app.routers.chat import router as chat_router
from app.routers.health import router as health_router
from app.routers.learners import router as learners_router
from app.routers.memorization import router as memorization_router
from app.routers.recommendations import router as recommendations_router
from app.routers.transcription import router as transcription_router
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "test.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                Poem(
                    slug="seed-poem",
                    title="Seed Poem",
                    author="Test Author",
                    language=PoemLanguage.en,
                    era=None,
                    themes=["nature"],
                    difficulty="easy",
                    excerpt="A short excerpt for tests.",
                    full_text="A short full text for tests.",
                )
            )
            await session.commit()

    asyncio.run(_setup_db())

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(health_router)
    api = APIRouter(prefix="/api/v1")
    api.include_router(chat_router)
    api.include_router(learners_router)
    api.include_router(recommendations_router)
    api.include_router(memorization_router)
    api.include_router(transcription_router)
    app.include_router(api)

    from app import database

    app.dependency_overrides[database.get_session] = _override_get_session

    with TestClient(app) as test_client:
        yield test_client

    engine.dispose()


@pytest.fixture
def onboarded_user(client: TestClient) -> int:
    user_id = 123456
    client.get(f"/api/v1/learners/{user_id}")
    client.patch(
        f"/api/v1/learners/{user_id}/profile",
        json={"onboarding_done": True, "prefers_english": True},
    )
    return user_id
