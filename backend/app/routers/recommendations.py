from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.tables import Poem, PoemLanguage
from app.schemas import NextRecommendationResponse, OutcomeRequest, PoemCatalogCard
from app.services.llm import chat_completion
from app.services.poem_placeholders import poem_body_for_display
from app.services.memorization import get_poem_by_slug
from app.services.recommendation import (
    attach_recommendation,
    get_or_create_learner,
    pick_next_poem,
    record_outcome,
)

router = APIRouter(prefix="/recommend", tags=["recommendations"])


@router.get("/themes", response_model=list[str])
async def catalog_theme_tags(session: AsyncSession = Depends(get_session)) -> list[str]:
    """Уникальные метки тем из всех стихов каталога (для выбора в профиле)."""
    q = await session.execute(select(Poem.themes))
    seen: set[str] = set()
    for (raw,) in q.all():
        for t in raw or []:
            s = str(t).strip()
            if s:
                seen.add(s)
    return sorted(seen, key=lambda x: (x.lower(), x))


@router.get("/card", response_model=PoemCatalogCard)
async def poem_catalog_card(
    poem_slug: str = Query(..., min_length=1, max_length=256),
    session: AsyncSession = Depends(get_session),
) -> PoemCatalogCard:
    poem = await get_poem_by_slug(session, poem_slug)
    if not poem:
        raise HTTPException(status_code=404, detail="Unknown poem slug")
    display_text = poem_body_for_display(poem)
    return PoemCatalogCard(
        poem_slug=poem.slug,
        title=poem.title,
        author=poem.author,
        language=poem.language.value,
        excerpt=display_text,
    )


def _sanitize_intro_prose(content: str) -> str:
    """Reject LLM output that imitates verse (many short lines)."""
    s = (content or "").strip()
    if not s:
        return ""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) >= 5:
        avg = sum(len(x) for x in lines) / len(lines)
        if avg < 52:
            return ""
    return s


def _norm_compact(s: str) -> str:
    return " ".join((s or "").lower().split())


def _intro_leaks_poem_body(intro: str, poem_body: str) -> bool:
    """True if intro repeats the opening of the catalog text (model must not echo the poem)."""
    pb = _norm_compact(poem_body)
    if len(pb) < 24:
        return False
    ni = _norm_compact(intro)
    if not ni:
        return False
    # Prefix of the stored poem must not appear inside the intro.
    if pb[:min(160, len(pb))] in ni:
        return True
    first_ln = (poem_body.strip().splitlines() or [""])[0].strip()
    if len(first_ln) >= 12 and _norm_compact(first_ln) in ni:
        return True
    return False


def _fallback_intro(poem_title: str, language: PoemLanguage) -> str:
    if language == PoemLanguage.ru:
        return (
            f"Ниже — полный текст «{poem_title}» из каталога (ничего не сочинено ботом). "
            "Можно читать и заучивать целиком."
        )
    return (
        f"The full poem text below comes from our catalog only (not invented). "
        f"Good luck memorizing \"{poem_title}\"."
    )


@router.post("/next", response_model=NextRecommendationResponse)
async def next_poem(
    telegram_user_id: int = Query(..., description="Telegram user id"),
    session: AsyncSession = Depends(get_session),
) -> NextRecommendationResponse:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    if not learner.onboarding_done:
        raise HTTPException(status_code=403, detail="onboarding_required")

    poem = await pick_next_poem(session, learner.id)
    if not poem:
        raise HTTPException(status_code=404, detail="No suitable poem found — adjust preferences.")

    await attach_recommendation(session, learner_id=learner.id, poem=poem)

    display_text = poem_body_for_display(poem)
    # Only the intro comes from the model; the poem is never in the prompt and is returned only in `excerpt`.
    intro_raw = await chat_completion(
        system=(
            "You write ONLY a short opening message (2–4 sentences) BEFORE the user will see a poem.\n"
            "Another system will insert the full poem text — not you. Your output must end after your prose intro.\n"
            "You only know: title, author, language, themes (below). You do NOT know any line of the poem.\n"
            "Rules:\n"
            "- Plain conversational prose only. One short paragraph.\n"
            "- Never write verse, rhyme, metre, or many short lines.\n"
            "- Never quote, invent, paraphrase, or summarize lines of the poem.\n"
            "- Match poem language (en → English; ru → Russian).\n"
            "- Encourage memorization briefly; you may mention themes.\n"
        ),
        user_messages=[
            {
                "role": "user",
                "content": (
                    "Metadata only — poem text is hidden from you:\n"
                    f"Title: {poem.title}\n"
                    f"Author: {poem.author}\n"
                    f"Language: {poem.language.value}\n"
                    f"Themes: {', '.join(poem.themes)}"
                ),
            }
        ],
        temperature=0.25,
        top_p=0.85,
        presence_penalty=0.0,
        max_tokens=220,
    )
    presentation = _sanitize_intro_prose(intro_raw) or _fallback_intro(poem.title, poem.language)
    if _intro_leaks_poem_body(presentation, display_text):
        presentation = _fallback_intro(poem.title, poem.language)

    return NextRecommendationResponse(
        poem_slug=poem.slug,
        title=poem.title,
        author=poem.author,
        language=poem.language.value,
        excerpt=display_text,
        presentation=presentation,
    )


@router.post("/outcome")
async def outcome(
    body: OutcomeRequest,
    telegram_user_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    learner = await get_or_create_learner(session, telegram_user_id=telegram_user_id, display_name=None)
    if not learner.onboarding_done:
        raise HTTPException(status_code=403, detail="onboarding_required")

    await record_outcome(session, learner_id=learner.id, poem_slug=body.poem_slug, outcome=body.outcome)
    return {"status": "recorded"}
