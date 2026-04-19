"""
Replace LLM placeholders with poem FULL TEXT from the database (no model-generated verse).

Syntax:
  [[poem:slug]]       — full poem text from Poem.full_text (fallback: excerpt)
  [[poem_full:slug]]  — same as [[poem:slug]] (alias)

Long texts are capped for Telegram (~3800 chars); rare overflow may be split client-side.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Poem

_PLACEHOLDER = re.compile(r"\[\[(poem_full|poem):([a-zA-Z0-9_-]+)\]\]")

# Telegram message soft limit — leave margin for titles / quiz footer
_MAX_DISPLAY_CHARS = 3800


def dedupe_placeholder_tokens(text: str) -> str:
    """Keep the first placeholder per slug."""
    seen_slug: set[str] = set()
    parts: list[str] = []
    last = 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(text[last : m.start()])
        slug = m.group(2)
        if slug not in seen_slug:
            seen_slug.add(slug)
            parts.append(m.group(0))
        last = m.end()
    parts.append(text[last:])
    return "".join(parts)


async def _poems_by_slugs(session: AsyncSession, slugs: list[str]) -> dict[str, Poem]:
    if not slugs:
        return {}
    uniq = list(dict.fromkeys(slugs))
    q = await session.execute(select(Poem).where(Poem.slug.in_(uniq)))
    return {p.slug: p for p in q.scalars().all()}


def _format_block(title: str, author: str, body: str) -> str:
    body = (body or "").strip()
    return f"\n\n«{title}» — {author}\n{body}\n"


def _full_poem_body(p: Poem) -> str:
    raw = (p.full_text or "").strip()
    if not raw:
        raw = (p.excerpt or "").strip()
    if not raw:
        return "[нет текста в базе]"
    if len(raw) > _MAX_DISPLAY_CHARS:
        return raw[:_MAX_DISPLAY_CHARS].rstrip() + "…"
    return raw


def poem_body_for_display(p: Poem) -> str:
    """Full poem text from DB for API/clients (Telegram-safe length)."""
    return _full_poem_body(p)


def expand_poem_placeholders_with_map(text: str, poems: dict[str, Poem]) -> str:
    def repl(_m: re.Match[str]) -> str:
        slug = _m.group(2)
        p = poems.get(slug)
        if not p:
            return f"\n\n[нет стиха «{slug}» в каталоге]\n"
        body = _full_poem_body(p)
        return _format_block(p.title, p.author, body)

    return _PLACEHOLDER.sub(repl, text)


async def expand_poem_placeholders(session: AsyncSession, text: str) -> str:
    text = dedupe_placeholder_tokens(text)
    slugs = [m.group(2) for m in _PLACEHOLDER.finditer(text)]
    if not slugs:
        return text
    poems = await _poems_by_slugs(session, slugs)
    return expand_poem_placeholders_with_map(text, poems)


def first_poem_slug_in_text(text: str) -> str | None:
    m = _PLACEHOLDER.search(text)
    return m.group(2) if m else None


_MULTIBLANK = re.compile(r"\n{3,}")


def strip_poem_placeholders(text: str) -> str:
    """Remove [[poem:]] / [[poem_full:]] tokens (e.g. during onboarding when poems must not appear)."""
    t = _PLACEHOLDER.sub("", text or "")
    t = _MULTIBLANK.sub("\n\n", t)
    return t.strip()
