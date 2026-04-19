from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Poem, PoemLanguage
from app.poem_csv_loader import DEFAULT_LIMIT_PER_LANG, load_csv_poems

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_poems_json_rows() -> list[dict[str, Any]]:
    """Hand-curated overrides in data/poems.json (same shape as CSV rows after merge)."""
    path = _DATA_DIR / "poems.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        lang = item.get("language")
        if lang not in ("en", "ru"):
            continue
        out.append(
            {
                "slug": slug,
                "title": str(item["title"])[:512],
                "author": str(item["author"])[:256],
                "language": lang,
                "era": item.get("era"),
                "themes": list(item.get("themes") or [])[:16],
                "difficulty": str(item.get("difficulty", "medium")),
                "excerpt": item["excerpt"],
                "full_text": item["full_text"],
            }
        )
    return out


def _merged_catalog_rows() -> list[dict[str, Any]]:
    """CSV poems first, then poems.json overwrites/adds by slug."""
    csv_rows = load_csv_poems(DEFAULT_LIMIT_PER_LANG)
    by_slug: dict[str, dict[str, Any]] = {r["slug"]: r for r in csv_rows}
    for row in _load_poems_json_rows():
        by_slug[row["slug"]] = row
    return list(by_slug.values())


async def seed_poems(session: AsyncSession) -> None:
    """
    Merge poem rows into the DB by slug on every startup.

    Sources: PoetryFoundation + russian CSV (bulk), then ``data/poems.json`` overrides.
    Stale SQLite rows get updated so ``full_text`` fixes apply without deleting the DB.
    """
    rows = _merged_catalog_rows()
    if not rows:
        raise RuntimeError(
            "No poems loaded from CSV. Ensure backend/data/PoetryFoundationData.csv and "
            "backend/data/russianPoetryWithTheme.csv exist."
        )

    result = await session.execute(select(Poem.slug))
    existing_slugs = set(result.scalars().all())

    for row in rows:
        slug = row["slug"]
        if slug in existing_slugs:
            poem = await session.scalar(select(Poem).where(Poem.slug == slug))
            if not poem:
                continue
            poem.title = row["title"][:512]
            poem.author = row["author"][:256]
            poem.language = PoemLanguage(row["language"])
            poem.era = row.get("era")
            poem.themes = list(row.get("themes") or [])
            poem.difficulty = row.get("difficulty", "medium")
            poem.excerpt = row["excerpt"]
            poem.full_text = row["full_text"]
        else:
            session.add(
                Poem(
                    slug=slug,
                    title=row["title"][:512],
                    author=row["author"][:256],
                    language=PoemLanguage(row["language"]),
                    era=row.get("era"),
                    themes=list(row.get("themes") or []),
                    difficulty=row.get("difficulty", "medium"),
                    excerpt=row["excerpt"],
                    full_text=row["full_text"],
                )
            )

    await session.commit()
