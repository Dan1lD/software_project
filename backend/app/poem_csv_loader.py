"""
Load poem records from project CSV dumps (stdlib csv only).
English: PoetryFoundationData.csv (Title, Poem, Poet, Tags).
Russian: russianPoetryWithTheme.csv (author, text, name, themes/*).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EN_CSV = DATA_DIR / "PoetryFoundationData.csv"
RU_CSV = DATA_DIR / "russianPoetryWithTheme.csv"
DEFAULT_LIMIT_PER_LANG = 100

_WS = re.compile(r"[ \t]+")
_MULTILINE_WS = re.compile(r"\n\s*\n\s*\n+")


def _clean_title(s: str | None) -> str:
    if not s:
        return ""
    t = s.replace("\r", "").strip()
    t = _WS.sub(" ", t)
    return t.strip()


def _normalize_body(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = _MULTILINE_WS.sub("\n\n", s)
    return s.strip()


def _excerpt(full: str, max_len: int = 480) -> str:
    full = _normalize_body(full)
    if len(full) <= max_len:
        return full
    cut = full[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;— ") + "…"


def _difficulty(n: int) -> str:
    if n < 500:
        return "easy"
    if n < 2000:
        return "medium"
    return "hard"


def _themes_from_tags(tags_raw: str | None) -> list[str]:
    if not tags_raw:
        return []
    parts = re.split(r"[,;|]", tags_raw)
    return [p.strip() for p in parts if p.strip()][:16]


_RU_THEME_KEYS = ("themes/item/0", "themes/item/1", "themes/item/2", "themes/item/3")


def load_english_rows(limit: int = DEFAULT_LIMIT_PER_LANG) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not EN_CSV.is_file():
        return out
    with EN_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        idx = 0
        for row in reader:
            poem = _normalize_body(row.get("Poem") or "")
            if len(poem) < 80:
                continue
            title = _clean_title(row.get("Title"))
            author = _clean_title(row.get("Poet")) or "Unknown"
            if not title:
                first_line = poem.split("\n", 1)[0].strip()
                title = first_line[:120] + ("…" if len(first_line) > 120 else "")
            themes = _themes_from_tags(row.get("Tags"))
            slug = f"en-pf-{idx:04d}"
            out.append(
                {
                    "slug": slug,
                    "title": title[:512],
                    "author": author[:256],
                    "language": "en",
                    "era": None,
                    "themes": themes,
                    "difficulty": _difficulty(len(poem)),
                    "excerpt": _excerpt(poem),
                    "full_text": poem,
                }
            )
            idx += 1
            if len(out) >= limit:
                break
    return out


def load_russian_rows(limit: int = DEFAULT_LIMIT_PER_LANG) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not RU_CSV.is_file():
        return out
    with RU_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        idx = 0
        for row in reader:
            poem = _normalize_body(row.get("text") or "")
            if len(poem) < 80:
                continue
            title = _clean_title(row.get("name"))
            author = _clean_title(row.get("author")) or "Неизвестный автор"
            if not title:
                first_line = poem.split("\n", 1)[0].strip()
                title = first_line[:120] + ("…" if len(first_line) > 120 else "")
            themes: list[str] = []
            for k in _RU_THEME_KEYS:
                v = (row.get(k) or "").strip()
                if v:
                    themes.append(v)
            themes = themes[:16]
            era_raw = row.get("date_from")
            era = str(era_raw).strip() if era_raw not in (None, "") else None
            if era:
                era = era[:128]
            slug = f"ru-th-{idx:04d}"
            out.append(
                {
                    "slug": slug,
                    "title": title[:512],
                    "author": author[:256],
                    "language": "ru",
                    "era": era,
                    "themes": themes,
                    "difficulty": _difficulty(len(poem)),
                    "excerpt": _excerpt(poem),
                    "full_text": poem,
                }
            )
            idx += 1
            if len(out) >= limit:
                break
    return out


def load_csv_poems(limit_per_lang: int = DEFAULT_LIMIT_PER_LANG) -> list[dict[str, Any]]:
    en = load_english_rows(limit_per_lang)
    ru = load_russian_rows(limit_per_lang)
    return en + ru
