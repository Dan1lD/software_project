from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas import ChatRequest, ChatResponse
from app.services.conversation import (
    apply_profile_updates,
    extract_recommend_slug,
    handle_user_message,
)
from app.services.recommendation import get_or_create_learner

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat_turn(body: ChatRequest, session: AsyncSession = Depends(get_session)) -> ChatResponse:
    learner = await get_or_create_learner(
        session,
        telegram_user_id=body.telegram_user_id,
        display_name=body.display_name,
    )
    if not learner.onboarding_done:
        raise HTTPException(status_code=403, detail="onboarding_required")

    reply, meta, placeholder_slug = await handle_user_message(
        session,
        learner=learner,
        text=body.message,
        last_bot_message=body.last_bot_message,
    )
    await apply_profile_updates(session, learner, meta)
    slug_hint = extract_recommend_slug(meta, reply) or placeholder_slug
    return ChatResponse(reply=reply, poem_slug_hint=slug_hint)
