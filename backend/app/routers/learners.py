from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.tables import LearnerPoem, MemorizationAttempt, Poem
from app.schemas import LearnerDashboard, LearnerProfilePatch, LearnerPublic, LearnerStatsResponse
from app.services.learner_stats_view import learner_stats_response_with_summary
from app.services.recommendation import get_or_create_learner, learner_stats

router = APIRouter(prefix="/learners", tags=["learners"])


@router.get("/{telegram_user_id}/stats", response_model=LearnerStatsResponse)
async def learner_stats_ep(telegram_user_id: int, session: AsyncSession = Depends(get_session)) -> LearnerStatsResponse:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    return await learner_stats_response_with_summary(session, learner)


@router.get("/{telegram_user_id}", response_model=LearnerPublic)
async def get_learner(telegram_user_id: int, session: AsyncSession = Depends(get_session)) -> LearnerPublic:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    memorized, learning, due_review = await learner_stats(session, learner.id)
    return LearnerPublic(
        telegram_user_id=learner.telegram_user_id,
        display_name=learner.display_name,
        prefers_english=learner.prefers_english,
        prefers_russian=learner.prefers_russian,
        themes=list(learner.themes or []),
        difficulty=learner.difficulty,
        notes=learner.notes,
        onboarding_done=learner.onboarding_done,
        onboarding_step=learner.onboarding_step,
        memorized_count=memorized,
        learning_count=learning,
        due_review_count=due_review,
    )


@router.patch("/{telegram_user_id}/profile", response_model=LearnerPublic)
async def patch_learner_profile(
    telegram_user_id: int,
    body: LearnerProfilePatch,
    session: AsyncSession = Depends(get_session),
) -> LearnerPublic:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    if body.prefers_english is not None:
        learner.prefers_english = body.prefers_english
    if body.prefers_russian is not None:
        learner.prefers_russian = body.prefers_russian
    if body.themes is not None:
        learner.themes = body.themes
    if body.difficulty is not None and str(body.difficulty) in {"easy", "medium", "hard"}:
        learner.difficulty = str(body.difficulty)
    if body.notes is not None:
        learner.notes = body.notes
    if body.onboarding_done is not None:
        learner.onboarding_done = body.onboarding_done
    if body.onboarding_step is not None:
        learner.onboarding_step = body.onboarding_step
    await session.commit()
    await session.refresh(learner)
    memorized, learning, due_review = await learner_stats(session, learner.id)
    return LearnerPublic(
        telegram_user_id=learner.telegram_user_id,
        display_name=learner.display_name,
        prefers_english=learner.prefers_english,
        prefers_russian=learner.prefers_russian,
        themes=list(learner.themes or []),
        difficulty=learner.difficulty,
        notes=learner.notes,
        onboarding_done=learner.onboarding_done,
        onboarding_step=learner.onboarding_step,
        memorized_count=memorized,
        learning_count=learning,
        due_review_count=due_review,
    )


@router.get("/{telegram_user_id}/dashboard", response_model=LearnerDashboard)
async def dashboard(telegram_user_id: int, session: AsyncSession = Depends(get_session)) -> LearnerDashboard:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    memorized, learning, due_review = await learner_stats(session, learner.id)

    lp_q = await session.execute(
        select(MemorizationAttempt, Poem)
        .join(Poem, MemorizationAttempt.poem_id == Poem.id)
        .where(MemorizationAttempt.learner_id == learner.id)
        .order_by(MemorizationAttempt.id.desc())
        .limit(8)
    )
    recent_rows = [{"poem": p.title, "score": a.score} for a, p in lp_q.all()]

    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=14)
    due_q = await session.execute(
        select(LearnerPoem, Poem)
        .join(Poem, LearnerPoem.poem_id == Poem.id)
        .where(
            LearnerPoem.learner_id == learner.id,
            LearnerPoem.next_review_at.is_not(None),
            LearnerPoem.next_review_at <= soon,
        )
        .order_by(LearnerPoem.next_review_at.asc())
        .limit(12)
    )
    upcoming = [
        {
            "slug": p.slug,
            "title": p.title,
            "due": lp.next_review_at.isoformat() if lp.next_review_at else None,
        }
        for lp, p in due_q.all()
    ]

    return LearnerDashboard(
        learner=LearnerPublic(
            telegram_user_id=learner.telegram_user_id,
            display_name=learner.display_name,
            prefers_english=learner.prefers_english,
            prefers_russian=learner.prefers_russian,
            themes=list(learner.themes or []),
            difficulty=learner.difficulty,
            notes=learner.notes,
            onboarding_done=learner.onboarding_done,
            onboarding_step=learner.onboarding_step,
            memorized_count=memorized,
            learning_count=learning,
            due_review_count=due_review,
        ),
        recent_attempts=recent_rows,
        upcoming_reviews=upcoming,
    )
