from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    u = make_url(database_url)
    if not u.drivername or "sqlite" not in u.drivername:
        return
    db = u.database
    if not db:
        return
    path = Path(db)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def _sqlite_add_onboarding_step(connection) -> None:
    from sqlalchemy import text

    r = connection.execute(text("PRAGMA table_info(learners)"))
    cols = {row[1] for row in r.fetchall()}
    if "onboarding_step" not in cols:
        connection.execute(
            text("ALTER TABLE learners ADD COLUMN onboarding_step INTEGER NOT NULL DEFAULT 0")
        )


async def init_db() -> None:
    _ensure_sqlite_parent_dir(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(_sqlite_add_onboarding_step)
