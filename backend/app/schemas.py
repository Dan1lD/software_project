from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LearnerPublic(BaseModel):
    telegram_user_id: int
    display_name: str | None
    prefers_english: bool
    prefers_russian: bool
    themes: list[str]
    difficulty: str
    notes: str | None
    onboarding_done: bool
    onboarding_step: int = 0
    memorized_count: int = 0
    learning_count: int = 0
    due_review_count: int = 0


class LearnerProfilePatch(BaseModel):
    prefers_english: bool | None = None
    prefers_russian: bool | None = None
    themes: list[str] | None = None
    difficulty: str | None = None
    notes: str | None = None
    onboarding_done: bool | None = None
    onboarding_step: int | None = None


class ChatRequest(BaseModel):
    telegram_user_id: int
    display_name: str | None = None
    message: str = Field(..., min_length=1, max_length=12000)


class ChatResponse(BaseModel):
    reply: str
    poem_slug_hint: str | None = None


class NextRecommendationResponse(BaseModel):
    poem_slug: str
    title: str
    author: str
    language: str
    excerpt: str
    presentation: str


class PoemCatalogCard(BaseModel):
    """Тот же текст, что показывается после /next (отрывок/полный текст из каталога)."""

    poem_slug: str
    title: str
    author: str
    language: str
    excerpt: str


class OutcomeRequest(BaseModel):
    poem_slug: str
    outcome: Literal["accepted", "skipped", "mastered"]


class PoemMetaResponse(BaseModel):
    slug: str
    title: str
    author: str
    language: str


class MemorizationRequest(BaseModel):
    poem_slug: str
    recall_text: str = Field(..., min_length=1, max_length=12000)


class MemorizationResponse(BaseModel):
    score: float
    feedback: str
    next_review_at: datetime | None
    poem_title: str
    poem_author: str
    poem_slug: str


class LearnerDashboard(BaseModel):
    learner: LearnerPublic
    recent_attempts: list[dict]
    upcoming_reviews: list[dict]


class LearnerStatsResponse(BaseModel):
    learner: LearnerPublic
    memorized_works: list[dict]
    upcoming_reviews: list[dict]
    summary_text: str = ""
