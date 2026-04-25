from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.tables import (Learner, LearnerPoem, LearnerPoemStatus, Poem,
                               PoemLanguage, RecommendationEvent,
                               RecommendationOutcome)
from app.schemas import LearnerPublic, LearnerStatsResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def get_or_create_learner(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    display_name: str | None,
) -> Learner:
    q = await session.execute(select(Learner).where(Learner.telegram_user_id == telegram_user_id))
    learner = q.scalar_one_or_none()
    if learner:
        if display_name and display_name != learner.display_name:
            learner.display_name = display_name
            await session.commit()
            await session.refresh(learner)
        return learner
    learner = Learner(
        telegram_user_id=telegram_user_id,
        display_name=display_name,
        prefers_english=False,
        prefers_russian=False,
        onboarding_done=False,
        onboarding_step=0,
    )
    session.add(learner)
    await session.commit()
    await session.refresh(learner)
    return learner


async def pick_next_poem(session: AsyncSession, learner_id: int) -> Poem | None:
    learner = await session.get(Learner, learner_id)
    if not learner:
        return None

    now = _utcnow()

    due = await session.execute(
        select(LearnerPoem)
        .options(selectinload(LearnerPoem.poem))
        .where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.next_review_at.is_not(None),
            LearnerPoem.next_review_at <= now,
            LearnerPoem.status.in_([LearnerPoemStatus.learning, LearnerPoemStatus.memorized]),
        )
        .order_by(LearnerPoem.next_review_at.asc())
        .limit(1)
    )
    lp = due.scalar_one_or_none()
    if lp and lp.poem:
        return lp.poem

    mastered_ids = (
        await session.execute(
            select(LearnerPoem.poem_id).where(
                LearnerPoem.learner_id == learner_id,
                LearnerPoem.status == LearnerPoemStatus.memorized,
            )
        )
    ).scalars().all()

    lang_filter = []
    if learner.prefers_english:
        lang_filter.append(PoemLanguage.en)
    if learner.prefers_russian:
        lang_filter.append(PoemLanguage.ru)
    if not lang_filter:
        lang_filter = [PoemLanguage.en, PoemLanguage.ru]

    exclude = set(mastered_ids)

    candidates_q = await session.execute(
        select(Poem).where(Poem.language.in_(lang_filter)).order_by(Poem.id.asc())
    )
    candidates = candidates_q.scalars().all()

    def difficulty_ok(p: Poem) -> bool:
        order = {"easy": 0, "medium": 1, "hard": 2}
        target = order.get(learner.difficulty, 1)
        return abs(order.get(p.difficulty, 1) - target) <= 1

    theme_pref = {t.lower() for t in (learner.themes or [])}

    def theme_overlap(p: Poem) -> int:
        if not theme_pref:
            return 0
        return len(theme_pref.intersection({x.lower() for x in (p.themes or [])}))

    fresh: list[Poem] = []
    skipped_ready: list[Poem] = []

    for p in candidates:
        if p.id in exclude:
            continue
        if not difficulty_ok(p):
            continue
        lp_row = await session.execute(
            select(LearnerPoem).where(
                LearnerPoem.learner_id == learner_id,
                LearnerPoem.poem_id == p.id,
            )
        )
        existing = lp_row.scalar_one_or_none()
        if existing is None:
            fresh.append(p)
        elif existing.status == LearnerPoemStatus.skipped:
            rec_at = _aware(existing.recommended_at) or now
            if now - rec_at >= timedelta(days=7):
                skipped_ready.append(p)

    fresh.sort(key=lambda p: (-theme_overlap(p), p.id))
    skipped_ready.sort(key=lambda p: (-theme_overlap(p), p.id))

    if fresh:
        return fresh[0]
    if skipped_ready:
        return skipped_ready[0]

    stmt = select(Poem).limit(1)
    if exclude:
        stmt = select(Poem).where(~Poem.id.in_(exclude)).limit(1)
    any_poem = await session.execute(stmt)
    return any_poem.scalar_one_or_none()


async def attach_recommendation(
    session: AsyncSession,
    *,
    learner_id: int,
    poem: Poem,
) -> LearnerPoem:
    q = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.poem_id == poem.id,
        )
    )
    lp = q.scalar_one_or_none()
    now = _utcnow()
    if lp:
        lp.status = LearnerPoemStatus.recommended
        lp.recommended_at = now
    else:
        lp = LearnerPoem(
            learner_id=learner_id,
            poem_id=poem.id,
            status=LearnerPoemStatus.recommended,
            recommended_at=now,
        )
        session.add(lp)

    session.add(
        RecommendationEvent(
            learner_id=learner_id,
            poem_id=poem.id,
            outcome=RecommendationOutcome.pending,
            detail="recommended",
        )
    )
    await session.commit()
    await session.refresh(lp)
    return lp


async def record_outcome(
    session: AsyncSession,
    *,
    learner_id: int,
    poem_slug: str,
    outcome: str,
) -> None:
    poem_q = await session.execute(select(Poem).where(Poem.slug == poem_slug))
    poem = poem_q.scalar_one_or_none()
    if not poem:
        return

    lp_q = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.poem_id == poem.id,
        )
    )
    lp = lp_q.scalar_one_or_none()

    now = _utcnow()
    if outcome == "accepted":
        status = LearnerPoemStatus.learning
        rec_out = RecommendationOutcome.accepted
    elif outcome == "skipped":
        status = LearnerPoemStatus.skipped
        rec_out = RecommendationOutcome.skipped
    else:
        status = LearnerPoemStatus.memorized
        rec_out = RecommendationOutcome.mastered

    if lp:
        lp.status = status
        lp.recommended_at = lp.recommended_at or now
        if status == LearnerPoemStatus.memorized:
            lp.last_score = 1.0
            lp.next_review_at = now + timedelta(days=14)
            lp.review_stage = lp.review_stage + 1
    else:
        lp = LearnerPoem(
            learner_id=learner_id,
            poem_id=poem.id,
            status=status,
            recommended_at=now,
            next_review_at=(now + timedelta(days=14)) if status == LearnerPoemStatus.memorized else None,
            review_stage=1 if status == LearnerPoemStatus.memorized else 0,
            last_score=1.0 if status == LearnerPoemStatus.memorized else None,
        )
        session.add(lp)

    session.add(
        RecommendationEvent(
            learner_id=learner_id,
            poem_id=poem.id,
            outcome=rec_out,
            detail=outcome,
        )
    )
    await session.commit()


async def learner_stats(session: AsyncSession, learner_id: int) -> tuple[int, int, int]:
    now = _utcnow()
    mem = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.status == LearnerPoemStatus.memorized,
        )
    )
    learning = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.status == LearnerPoemStatus.learning,
        )
    )
    due = await session.execute(
        select(LearnerPoem).where(
            LearnerPoem.learner_id == learner_id,
            LearnerPoem.next_review_at.is_not(None),
            LearnerPoem.next_review_at <= now,
        )
    )
    return len(mem.scalars().all()), len(learning.scalars().all()), len(due.scalars().all())


async def build_learner_stats_response(session: AsyncSession, *, learner: Learner) -> LearnerStatsResponse:
    """Сводка для /stats: только выученные произведения и ближайшие повторы."""
    memorized, learning, due_review = await learner_stats(session, learner.id)

    learned_q = await session.execute(
        select(LearnerPoem, Poem)
        .join(Poem, LearnerPoem.poem_id == Poem.id)
        .where(
            LearnerPoem.learner_id == learner.id,
            LearnerPoem.status == LearnerPoemStatus.memorized,
        )
        .order_by(Poem.title.asc())
    )
    memorized_works = [
        {"slug": p.slug, "title": p.title, "author": p.author} for lp, p in learned_q.all()
    ]

    now = _utcnow()
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
        .limit(24)
    )
    upcoming = [
        {
            "slug": p.slug,
            "title": p.title,
            "due": lp.next_review_at.isoformat() if lp.next_review_at else None,
        }
        for lp, p in due_q.all()
    ]

    pub = LearnerPublic(
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

    return LearnerStatsResponse(
        learner=pub,
        memorized_works=memorized_works,
        upcoming_reviews=upcoming,
    )
