from __future__ import annotations

import json
from typing import Any

from app.models.tables import ChatMessage, Learner, LearnerPoem, MemorizationAttempt, Poem
from app.services.learner_stats_view import learner_stats_reply_text
from app.services.llm import chat_completion, extract_json_block
from app.services.poem_placeholders import expand_poem_placeholders
from app.services.recommendation import learner_stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


async def append_message(session: AsyncSession, learner_id: int, role: str, content: str) -> None:
    session.add(ChatMessage(learner_id=learner_id, role=role, content=content))
    await session.commit()


async def recent_history(session: AsyncSession, learner_id: int, limit: int = 14) -> list[dict[str, str]]:
    q = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.learner_id == learner_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    )
    rows = list(reversed(q.scalars().all()))
    return [{"role": r.role, "content": r.content} for r in rows]


_CONTINUITY_MAX = 12000


async def fetch_last_assistant_content(session: AsyncSession, learner_id: int) -> str | None:
    q = await session.execute(
        select(ChatMessage.content)
        .where(ChatMessage.learner_id == learner_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    raw = q.scalar_one_or_none()
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _same_message_body(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.strip() == b.strip()


def build_continuity_prefix(
    *,
    history_tail: list[dict[str, str]],
    client_last_bot: str | None,
    db_last_assistant: str | None,
) -> str:
    """Текст перед блоком профиля/каталога: что бот только что писал пользователю (видно модели явно)."""
    c = (client_last_bot or "").strip()
    if c:
        return (
            "Последнее сообщение бота пользователю (контекст до этого сообщения пользователя):\n---\n"
            + c[:_CONTINUITY_MAX]
            + "\n---\n\n"
        )
    ldb = (db_last_assistant or "").strip()
    if not ldb:
        return ""
    last = history_tail[-1] if history_tail else None
    if last and last.get("role") == "assistant" and _same_message_body(last.get("content"), ldb):
        return ""
    return (
        "Последнее сообщение ассистента в сохранённом диалоге (до текущего сообщения пользователя):\n---\n"
        + ldb[:_CONTINUITY_MAX]
        + "\n---\n\n"
    )


async def profile_snapshot(session: AsyncSession, learner: Learner) -> dict[str, Any]:
    memorized, learning, due_review = await learner_stats(session, learner.id)
    lp_rows = await session.execute(
        select(LearnerPoem)
        .options(selectinload(LearnerPoem.poem))
        .where(LearnerPoem.learner_id == learner.id)
    )
    items = []
    for lp in lp_rows.scalars().all():
        if not lp.poem:
            continue
        items.append(
            {
                "slug": lp.poem.slug,
                "title": lp.poem.title,
                "status": lp.status.value,
                "last_score": lp.last_score,
            }
        )
    return {
        "telegram_user_id": learner.telegram_user_id,
        "prefers_english": learner.prefers_english,
        "prefers_russian": learner.prefers_russian,
        "themes": learner.themes,
        "difficulty": learner.difficulty,
        "notes": learner.notes,
        "onboarding_done": learner.onboarding_done,
        "counts": {
            "memorized": memorized,
            "learning": learning,
            "due_review": due_review,
        },
        "poems": items[:24],
    }


async def recent_attempts(session: AsyncSession, learner_id: int, limit: int = 5) -> list[dict[str, Any]]:
    q = await session.execute(
        select(MemorizationAttempt)
        .where(MemorizationAttempt.learner_id == learner_id)
        .order_by(MemorizationAttempt.id.desc())
        .limit(limit)
    )
    out = []
    for a in q.scalars().all():
        poem = await session.get(Poem, a.poem_id)
        out.append(
            {
                "poem": poem.title if poem else "?",
                "score": a.score,
                "snippet": (a.user_text or "")[:120],
            }
        )
    return out


def _looks_like_verse_layout(s: str) -> bool:
    """Heuristic: many short lines ≈ poetry / pasted verse (not coaching prose)."""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    avg = sum(len(x) for x in lines) / len(lines)
    # Russian/EN verse lines are usually short; prose paragraphs are longer on average.
    if len(lines) >= 5 and avg < 52:
        return True
    if len(lines) >= 3 and avg < 36:
        return True
    return False


def _sanitize_coach_text(content: str, *, strict: bool = False) -> str:
    """Drop prose that looks like pasted verse. ``strict``: stricter thresholds (when a poem segment is also shown)."""
    s = (content or "").strip()
    if not s:
        return ""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    warn = (
        "_(коуч-текст похож на стихотворную верстку и скрыт; "
        "стих подставляется только через сегменты poem/poem_full.)_"
    )
    if strict:
        if _looks_like_verse_layout(s):
            return ""
    else:
        if len(lines) >= 5:
            avg = sum(len(x) for x in lines) / len(lines)
            if avg < 52:
                return warn
    return s


_QUIZ_INVITE_FOOTER = (
    "\n\n———————————————\n"
    "Проверьте наизусть: нажмите /quiz и пришлите следующим сообщением свой текст по памяти "
    "(оценка автоматическая), либо начните сообщение со слов «проверь» / «quiz»."
)


def _system_prompt() -> str:
    return (
        "You are Poetry Pal. Reply with ONE JSON object ONLY. No markdown fences. No text before or after JSON.\n"
        "Schema:\n"
        "{\n"
        '  "reply_segments": [\n'
        '    {"type": "text", "content": "short coaching only: questions, encouragement, tips. '
        "NO poem lines, NO stanza breaks imitating poetry, NO quotation of verses. Plain prose.},\n"
        '    {"type": "poem", "slug": "must-exist-in-catalog"},\n'
        '    {"type": "poem_full", "slug": "must-exist-in-catalog"}\n'
        "  ],\n"
        '  "update_profile": null,\n'
        '  "recommend_slug": null\n'
        "}\n"
        "- Put the actual poem ONLY via segments type poem or poem_full. The server replaces them with the "
        "FULL poem text from the database (same for poem and poem_full — use one or the other; same slug once).\n"
        "- Slugs must match the catalog list in the user message.\n"
        "- Do not paste poem lines inside \"text\" segments.\n"
        '- update_profile: keys prefers_english, prefers_russian, themes, difficulty, notes, onboarding_done or null.\n'
        "- recommend_slug: catalog slug if user clearly wants next pick, else null.\n"
        "Tone in text segments: warm, concise.\n"
    )


def _parse_structured_reply(raw: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """
    Parse JSON-only assistant output into placeholder line + meta.
    Returns (reply_core_with_placeholders, meta_dict, first_poem_slug).
    """
    raw = (raw or "").strip()
    data: dict[str, Any] | None = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        blk = extract_json_block(raw)
        if isinstance(blk, dict) and "reply_segments" in blk:
            data = blk
    if not isinstance(data, dict):
        return "", None, None

    segments = data.get("reply_segments")
    if not isinstance(segments, list):
        segments = []

    has_poem_segment = any(
        isinstance(s, dict) and s.get("type") in ("poem", "poem_full") for s in segments
    )

    pieces: list[str] = []
    first_slug: str | None = None
    seen_poem_slug: set[str] = set()

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        t = seg.get("type")
        if t == "text":
            body = _sanitize_coach_text(str(seg.get("content", "")), strict=has_poem_segment)
            if body:
                pieces.append(body)
        elif t == "poem":
            slug = str(seg.get("slug", "")).strip()
            if slug and slug not in seen_poem_slug:
                seen_poem_slug.add(slug)
                pieces.append(f"[[poem:{slug}]]")
                if first_slug is None:
                    first_slug = slug
        elif t == "poem_full":
            slug = str(seg.get("slug", "")).strip()
            if slug and slug not in seen_poem_slug:
                seen_poem_slug.add(slug)
                pieces.append(f"[[poem_full:{slug}]]")
                if first_slug is None:
                    first_slug = slug

    reply_core = "\n\n".join(pieces)

    meta: dict[str, Any] = {}
    up = data.get("update_profile")
    if isinstance(up, dict):
        meta["update_profile"] = up
    rs = data.get("recommend_slug")
    if isinstance(rs, str) and rs.strip():
        meta["recommend_slug"] = rs.strip()

    return reply_core, (meta if meta else None), first_slug


_FALLBACK_PARSE = (
    "Не удалось разобрать ответ модели (нужен один JSON-объект). Попробуйте ещё раз или короче."
)


def _is_stats_command(text: str) -> bool:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    return first.split("@", 1)[0] == "/stats"


async def handle_user_message(
    session: AsyncSession,
    *,
    learner: Learner,
    text: str,
    last_bot_message: str | None = None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    if _is_stats_command(text):
        reply_text = await learner_stats_reply_text(session, learner)
        await append_message(session, learner.id, "user", text)
        await append_message(session, learner.id, "assistant", reply_text)
        return reply_text, None, None

    history = await recent_history(session, learner.id, limit=14)
    db_last_assistant = await fetch_last_assistant_content(session, learner.id)
    continuity = build_continuity_prefix(
        history_tail=history[-10:] if history else [],
        client_last_bot=last_bot_message,
        db_last_assistant=db_last_assistant,
    )

    snap = await profile_snapshot(session, learner)
    attempts = await recent_attempts(session, learner.id)

    catalog_rows = (
        await session.execute(
            select(Poem.slug, Poem.title, Poem.author, Poem.language, Poem.themes).order_by(Poem.id)
        )
    ).all()
    catalog_lines: list[str] = []
    for row in catalog_rows:
        th = ", ".join(row.themes or []) if row.themes else "—"
        catalog_lines.append(
            f"[{row.slug}] {row.title} — {row.author} ({row.language.value}); themes: {th}"
        )

    profile_blob = json.dumps(snap, ensure_ascii=False)
    attempts_blob = json.dumps(attempts, ensure_ascii=False)

    user_payload = continuity + (
        f"Learner profile JSON:\n{profile_blob}\n\n"
        f"Recent memorization tries:\n{attempts_blob}\n\n"
        "Poem catalog (slugs for reply_segments only):\n"
        + "\n".join(catalog_lines)
        + "\n\nUser message:\n"
        + text
    )

    messages = history[-10:] + [{"role": "user", "content": user_payload}]

    raw = await chat_completion(
        system=_system_prompt(),
        user_messages=messages,
        temperature=0.12,
        top_p=0.75,
        presence_penalty=0.05,
    )

    reply_core, meta, placeholder_slug = _parse_structured_reply(raw)

    if not reply_core.strip():
        reply_core = _FALLBACK_PARSE
        meta = extract_json_block(raw)
        placeholder_slug = None

    reply_expanded = await expand_poem_placeholders(session, reply_core)
    if placeholder_slug:
        reply_expanded = reply_expanded.rstrip() + _QUIZ_INVITE_FOOTER

    await append_message(session, learner.id, "user", text)
    await append_message(session, learner.id, "assistant", reply_expanded)

    return reply_expanded, meta, placeholder_slug


async def apply_profile_updates(session: AsyncSession, learner: Learner, meta: dict[str, Any] | None) -> None:
    if not meta:
        return
    upd = meta.get("update_profile") if isinstance(meta, dict) else None
    if not isinstance(upd, dict):
        return
    if "prefers_english" in upd:
        learner.prefers_english = bool(upd["prefers_english"])
    if "prefers_russian" in upd:
        learner.prefers_russian = bool(upd["prefers_russian"])
    if "themes" in upd and isinstance(upd["themes"], list):
        learner.themes = [str(x) for x in upd["themes"]][:16]
    if "difficulty" in upd:
        d = str(upd["difficulty"])
        if d in {"easy", "medium", "hard"}:
            learner.difficulty = d
    if "notes" in upd:
        learner.notes = upd["notes"] if isinstance(upd["notes"], str) else learner.notes
    if "onboarding_done" in upd:
        learner.onboarding_done = bool(upd["onboarding_done"])
    if "onboarding_step" in upd:
        try:
            learner.onboarding_step = int(upd["onboarding_step"])
        except (TypeError, ValueError):
            pass
    await session.commit()
    await session.refresh(learner)


def extract_recommend_slug(meta: dict[str, Any] | None, text: str) -> str | None:
    if isinstance(meta, dict):
        slug = meta.get("recommend_slug")
        if isinstance(slug, str) and slug.strip():
            return slug.strip()
    return None
