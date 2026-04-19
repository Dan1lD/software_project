from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import MemorizationRequest, MemorizationResponse, PoemMetaResponse
from app.services.llm import judge_memorization
from app.services.memorization import get_poem_by_slug, save_attempt, schedule_after_attempt
from app.services.recommendation import get_or_create_learner

router = APIRouter(prefix="/memorization", tags=["memorization"])


@router.get("/poem", response_model=PoemMetaResponse)
async def get_poem_meta(
    poem_slug: str = Query(..., min_length=1, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> PoemMetaResponse:
    poem = await get_poem_by_slug(session, poem_slug)
    if not poem:
        raise HTTPException(status_code=404, detail="Unknown poem slug")
    return PoemMetaResponse(
        slug=poem.slug,
        title=poem.title,
        author=poem.author,
        language=poem.language.value,
    )


@router.post("/check", response_model=MemorizationResponse)
async def check_recall(
    body: MemorizationRequest,
    telegram_user_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> MemorizationResponse:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    if not learner.onboarding_done:
        raise HTTPException(status_code=403, detail="onboarding_required")

    poem = await get_poem_by_slug(session, body.poem_slug)
    if not poem:
        raise HTTPException(status_code=404, detail="Unknown poem slug")

    reference = (poem.full_text or poem.excerpt or "").strip()
    if len(reference) > 14000:
        reference = reference[:14000].rstrip() + "…"

    score, feedback = await judge_memorization(
        poem_title=poem.title,
        poem_author=poem.author,
        excerpt=reference,
        recall=body.recall_text,
    )
    await save_attempt(
        session,
        learner_id=learner.id,
        poem_id=poem.id,
        user_text=body.recall_text,
        score=score,
        feedback=feedback,
    )
    next_at = await schedule_after_attempt(session, learner_id=learner.id, poem_id=poem.id, score=score)
    return MemorizationResponse(
        score=score,
        feedback=feedback,
        next_review_at=next_at,
        poem_title=poem.title,
        poem_author=poem.author,
        poem_slug=poem.slug,
    )
