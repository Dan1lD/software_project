from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.tables import (LearnerPoem, LearnerPoemStatus,
                               MemorizationAttempt, Poem)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


INTERVALS_DAYS = [1, 3, 7, 14, 30]


async def schedule_after_attempt(
    session: AsyncSession,
    *,
    learner_id: int,
    poem_id: int,
    score: float,
) -> datetime | None:
    q = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.poem_id == poem_id,
        )
    )
    lp = q.scalar_one_or_none()
    now = _utcnow()
    if not lp:
        lp = LearnerPoem(
            learner_id=learner_id,
            poem_id=poem_id,
            status=LearnerPoemStatus.learning,
            recommended_at=now,
            review_stage=0,
        )
        session.add(lp)

    lp.last_score = score
    if score >= 0.85:
        lp.status = LearnerPoemStatus.memorized
        lp.review_stage = min(lp.review_stage + 1, len(INTERVALS_DAYS) - 1)
        days = INTERVALS_DAYS[lp.review_stage]
        lp.next_review_at = now + timedelta(days=days)
    elif score >= 0.55:
        lp.status = LearnerPoemStatus.learning
        lp.review_stage = max(0, lp.review_stage - 1)
        lp.next_review_at = now + timedelta(days=3)
    else:
        lp.status = LearnerPoemStatus.learning
        lp.next_review_at = now + timedelta(days=1)

    await session.commit()
    await session.refresh(lp)
    return lp.next_review_at


async def save_attempt(
    session: AsyncSession,
    *,
    learner_id: int,
    poem_id: int,
    user_text: str,
    score: float,
    feedback: str | None,
) -> MemorizationAttempt:
    row = MemorizationAttempt(
        learner_id=learner_id,
        poem_id=poem_id,
        user_text=user_text,
        score=score,
        feedback=feedback,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_poem_by_slug(session: AsyncSession, slug: str) -> Poem | None:
    q = await session.execute(select(Poem).where(Poem.slug == slug))
    return q.scalar_one_or_none()
