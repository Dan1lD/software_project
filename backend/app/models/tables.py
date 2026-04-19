from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PoemLanguage(str, enum.Enum):
    en = "en"
    ru = "ru"


class LearnerPoemStatus(str, enum.Enum):
    recommended = "recommended"
    learning = "learning"
    memorized = "memorized"
    skipped = "skipped"


class RecommendationOutcome(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    skipped = "skipped"
    mastered = "mastered"


class Poem(Base):
    __tablename__ = "poems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    author: Mapped[str] = mapped_column(String(256))
    language: Mapped[PoemLanguage] = mapped_column(Enum(PoemLanguage), index=True)
    era: Mapped[str | None] = mapped_column(String(128), nullable=True)
    themes: Mapped[list[str]] = mapped_column(SQLiteJSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(32), default="medium")  # easy|medium|hard
    excerpt: Mapped[str] = mapped_column(Text)
    full_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    learner_links: Mapped[list[LearnerPoem]] = relationship(back_populates="poem")


class Learner(Base):
    __tablename__ = "learners"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    prefers_english: Mapped[bool] = mapped_column(Boolean, default=False)
    prefers_russian: Mapped[bool] = mapped_column(Boolean, default=False)
    themes: Mapped[list[str]] = mapped_column(SQLiteJSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(32), default="medium")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Wizard: 0=languages, 1=themes (кнопки из каталога), 2=difficulty; ignored when onboarding_done.
    onboarding_step: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    learner_poems: Mapped[list[LearnerPoem]] = relationship(back_populates="learner")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="learner")


class LearnerPoem(Base):
    __tablename__ = "learner_poems"
    __table_args__ = (UniqueConstraint("learner_id", "poem_id", name="uq_learner_poem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    poem_id: Mapped[int] = mapped_column(ForeignKey("poems.id"), index=True)
    status: Mapped[LearnerPoemStatus] = mapped_column(
        Enum(LearnerPoemStatus), default=LearnerPoemStatus.recommended
    )
    recommended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_stage: Mapped[int] = mapped_column(Integer, default=0)
    last_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    learner: Mapped[Learner] = relationship(back_populates="learner_poems")
    poem: Mapped[Poem] = relationship(back_populates="learner_links")


class RecommendationEvent(Base):
    __tablename__ = "recommendation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    poem_id: Mapped[int] = mapped_column(ForeignKey("poems.id"), index=True)
    outcome: Mapped[RecommendationOutcome] = mapped_column(Enum(RecommendationOutcome))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MemorizationAttempt(Base):
    __tablename__ = "memorization_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    poem_id: Mapped[int] = mapped_column(ForeignKey("poems.id"), index=True)
    user_text: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    learner_id: Mapped[int] = mapped_column(ForeignKey("learners.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    learner: Mapped[Learner] = relationship(back_populates="messages")
