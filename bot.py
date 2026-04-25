"""
Telegram frontend for Poetry CRS — proxies text/voice to FastAPI backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from telebot.async_telebot import AsyncTeleBot

load_dotenv()

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000").rstrip("/")

bot = AsyncTeleBot(BOT_TOKEN)

HELP_TEXT = (
    "Привет! Я Poetry Pal — помогу выбрать классические стихи на английском и русском, "
    "потренировать память и напомню о повторах.\n\n"
    "Сначала нужно заполнить профиль — без этого стихотворения из каталога недоступны.\n\n"
    "Команды:\n"
    "/setup — заново пройти анкету\n"
    "/next — следующая рекомендация\n"
    "/quiz (или кнопка «Проверка» под рекомендацией) — следующее текстовое сообщение = проверка по стиху с /next\n"
    "/profile — предпочтения для рекомендаций\n"
    "/stats — выученные произведения и ближайшие повторы\n"
    "/review — что повторить в ближайшие две недели\n"
    "/help — это сообщение\n\n"
    "Можно писать текстом или голосом."
)


async def api_chat(
    user_id: int,
    text: str,
    display_name: str | None = None,
    *,
    last_bot_message: str | None = None,
) -> tuple[str, str | None]:
    payload: dict[str, Any] = {"telegram_user_id": user_id, "message": text, "display_name": display_name}
    if last_bot_message and str(last_bot_message).strip():
        payload["last_bot_message"] = str(last_bot_message).strip()[:14000]
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{API_URL}/api/v1/chat", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["reply"], data.get("poem_slug_hint")


async def api_next(user_id: int) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{API_URL}/api/v1/recommend/next", params={"telegram_user_id": user_id})
        r.raise_for_status()
        return r.json()


async def api_profile(user_id: int) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{API_URL}/api/v1/learners/{user_id}")
        r.raise_for_status()
        return r.json()


async def api_patch_profile(user_id: int, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.patch(f"{API_URL}/api/v1/learners/{user_id}/profile", json=body)
        r.raise_for_status()
        return r.json()


async def api_dashboard(user_id: int) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{API_URL}/api/v1/learners/{user_id}/dashboard")
        r.raise_for_status()
        return r.json()


async def api_stats(user_id: int) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{API_URL}/api/v1/learners/{user_id}/stats")
        r.raise_for_status()
        return r.json()


async def api_outcome(user_id: int, slug: str, outcome: str) -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{API_URL}/api/v1/recommend/outcome",
            params={"telegram_user_id": user_id},
            json={"poem_slug": slug, "outcome": outcome},
        )
        r.raise_for_status()


async def api_check(user_id: int, slug: str, recall: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{API_URL}/api/v1/memorization/check",
            params={"telegram_user_id": user_id},
            json={"poem_slug": slug, "recall_text": recall},
        )
        r.raise_for_status()
        return r.json()


async def api_poem_meta(slug: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{API_URL}/api/v1/memorization/poem", params={"poem_slug": slug})
        r.raise_for_status()
        return r.json()


async def api_poem_catalog_card(slug: str) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"{API_URL}/api/v1/recommend/card", params={"poem_slug": slug})
        r.raise_for_status()
        return r.json()


def _poem_label_from_api(meta: dict) -> str:
    title = (meta.get("title") or "").strip()
    author = (meta.get("author") or "").strip()
    if title and author:
        return f"«{title}» — {author}"
    if title:
        return f"«{title}»"
    return (meta.get("slug") or "?").strip() or "?"


async def transcribe_voice(file_bytes: bytes, filename: str) -> str:
    url = f"{API_URL}/api/v1/speech/transcribe"
    async with httpx.AsyncClient(timeout=300.0) as client:
        files = {"audio": (filename, file_bytes, "application/octet-stream")}
        r = await client.post(url, files=files)
        if r.status_code == 503:
            raise RuntimeError(r.text[:800] or "speech_unavailable")
        r.raise_for_status()
        try:
            data = r.json()
        except json.JSONDecodeError:
            log.warning("transcribe non-json: %s", r.text[:300])
            raise RuntimeError("bad_response") from None
        return (data.get("text") or "").strip()


# Стих для заучивания и /quiz — только из /next и кнопок под рекомендацией (не из чата с LLM).
MEMORIZE_SLUG: dict[int, str | None] = {}
# Последний slug, по которому только что показали результат проверки (кнопка «Повторить»).
LAST_GRADED_SLUG: dict[int, str | None] = {}
# Последний slug из ответа чата (коуч мог показать другое произведение — не затирает MEMORIZE_SLUG).
CHAT_POEM_HINT: dict[int, str | None] = {}
QUIZ_PENDING: dict[int, bool] = {}
# Последнее исходящее сообщение бота в чат (для контекста LLM при следующем сообщении пользователя).
LAST_BOT_OUTBOUND_TEXT: dict[int, str] = {}
# Анкета шаг «темы»: пары (подпись кнопки, каноническое значение для БД); выбор по telegram user id.
THEME_PAIRS: dict[int, list[tuple[str, str]]] = {}
THEME_SELECTION: dict[int, set[str]] = {}

# Подпись на кнопке → строка в learner.themes (пересечение с poem.themes при рекомендации).
ONBOARDING_EN_THEMES: tuple[tuple[str, str], ...] = (
    ("Love", "love"),
    ("War & Conflict", "war"),
    ("Nature", "nature"),
)
ONBOARDING_RU_THEMES: tuple[tuple[str, str], ...] = (
    ("Любовь", "О любви"),
    ("Дружба", "О дружбе"),
    ("Война", "Военные"),
)


def theme_choice_pairs(prefers_en: bool, prefers_ru: bool) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if prefers_en:
        pairs.extend(ONBOARDING_EN_THEMES)
    if prefers_ru:
        pairs.extend(ONBOARDING_RU_THEMES)
    if not pairs:
        pairs.extend(ONBOARDING_EN_THEMES)
        pairs.extend(ONBOARDING_RU_THEMES)
    return pairs

TG_MSG_LIMIT = 4096


def remember_bot_outbound_text(chat_id: int, content: str | None) -> None:
    text = (content or "").strip()
    if not text:
        return
    LAST_BOT_OUTBOUND_TEXT[chat_id] = text[:12000]


def _slug_for_keyword_check(chat_id: int) -> str | None:
    """Для «проверь» в тексте: сначала стих с /next, иначе последний из чата."""
    return MEMORIZE_SLUG.get(chat_id) or CHAT_POEM_HINT.get(chat_id)


def _profile_onboarding_complete(prof: dict) -> bool:
    """Only explicit True from API — never treat errors or missing keys as «done»."""
    return prof.get("onboarding_done") is True


_ONBOARDING_WELCOME = (
    "Добро пожаловать в Poetry Pal.\n\n"
    "Заполним короткий профиль — без этого нельзя открывать стихи из каталога и общаться с ИИ-коучем."
)

_ONBOARDING_COMPLETE = (
    "Профиль сохранён. Теперь можно писать в чат (коуч на базе ИИ), нажать /next за рекомендацией стиха "
    "или /quiz для проверки наизусть."
)

_START_ALREADY_DONE = (
    "Профиль уже заполнен. Пишите в чат, /next — новый стих из каталога, /profile — настройки, /help — команды."
)


def onboarding_lang_keyboard():
    from telebot import types

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("English", callback_data="ob:lang:en"),
        types.InlineKeyboardButton("Русский", callback_data="ob:lang:ru"),
    )
    kb.add(types.InlineKeyboardButton("Оба языка / Both", callback_data="ob:lang:both"))
    return kb


def onboarding_diff_keyboard():
    from telebot import types

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("Лёгкая", callback_data="ob:diff:easy"),
        types.InlineKeyboardButton("Средняя", callback_data="ob:diff:medium"),
        types.InlineKeyboardButton("Сложная", callback_data="ob:diff:hard"),
    )
    return kb


def onboarding_themes_keyboard(user_id: int):
    from telebot import types

    pairs = THEME_PAIRS.get(user_id) or []
    sel = THEME_SELECTION.setdefault(user_id, set())
    kb = types.InlineKeyboardMarkup()
    row = []
    for i, (caption, canon) in enumerate(pairs):
        display = caption if len(caption) <= 30 else caption[:27] + "…"
        label = f"✓ {display}" if canon in sel else display
        row.append(types.InlineKeyboardButton(label, callback_data=f"ob:th:{i}"))
        if len(row) >= 2:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(
        types.InlineKeyboardButton("Очистить выбор", callback_data="ob:th:clear"),
        types.InlineKeyboardButton("Без тем", callback_data="ob:th:skip"),
    )
    kb.add(types.InlineKeyboardButton("Готово", callback_data="ob:th:done"))
    return kb


async def send_onboarding_themes_step(chat_id: int, user_id: int) -> None:
    try:
        p = await api_profile(user_id)
    except httpx.HTTPError as e:
        await bot.send_message(chat_id, f"Не удалось загрузить профиль: {e!s}")
        return
    pairs = theme_choice_pairs(bool(p.get("prefers_english")), bool(p.get("prefers_russian")))
    THEME_PAIRS[user_id] = pairs
    THEME_SELECTION[user_id] = set()
    await bot.send_message(
        chat_id,
        "Шаг 2 из 3. Выберите интересующие темы (можно несколько), затем «Готово». "
        "«Без тем» — без предпочтений по темам.",
        reply_markup=onboarding_themes_keyboard(user_id),
    )


async def resume_onboarding(chat_id: int, user_id: int) -> None:
    p = await api_profile(user_id)
    if _profile_onboarding_complete(p):
        return
    step = int(p.get("onboarding_step") or 0)
    await bot.send_message(chat_id, _ONBOARDING_WELCOME)
    if step == 0:
        await bot.send_message(chat_id, "Шаг 1 из 3. Выберите языки стихов:", reply_markup=onboarding_lang_keyboard())
    elif step == 1:
        await send_onboarding_themes_step(chat_id, user_id)
    else:
        await bot.send_message(
            chat_id,
            "Шаг 3 из 3. Выберите комфортную сложность:",
            reply_markup=onboarding_diff_keyboard(),
        )


async def handle_onboarding_text(chat_id: int, user_id: int, text: str) -> bool:
    """Handle theme step; returns True if consumed."""
    p = await api_profile(user_id)
    if _profile_onboarding_complete(p):
        return False
    step = int(p.get("onboarding_step") or 0)
    if step != 1:
        if step == 0:
            await resume_onboarding(chat_id, user_id)
        elif step == 2:
            await bot.send_message(chat_id, "Выберите сложность кнопками ниже.", reply_markup=onboarding_diff_keyboard())
        return True
    await bot.send_message(
        chat_id,
        "Темы задаются только кнопками под сообщением анкеты (несколько тем можно включить, затем «Готово»).",
    )
    return True


async def onboarding_callback(c):
    """Inline: ob:lang:*, ob:th:* (фиксированные темы EN/RU по языку профиля), ob:diff:*"""
    data = c.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "ob":
        await bot.answer_callback_query(c.id)
        return
    _, kind, code = parts
    uid = c.from_user.id
    chat_id = c.message.chat.id

    if kind == "lang":
        if code == "en":
            patch = {"prefers_english": True, "prefers_russian": False, "onboarding_step": 1}
        elif code == "ru":
            patch = {"prefers_english": False, "prefers_russian": True, "onboarding_step": 1}
        elif code == "both":
            patch = {"prefers_english": True, "prefers_russian": True, "onboarding_step": 1}
        else:
            await bot.answer_callback_query(c.id)
            return
        await api_patch_profile(uid, patch)
        await bot.answer_callback_query(c.id, text="Сохранено")
        await send_onboarding_themes_step(chat_id, uid)
        return

    if kind == "th":
        if code == "done":
            chosen = sorted(THEME_SELECTION.get(uid, set()))[:16]
            await api_patch_profile(uid, {"themes": chosen, "onboarding_step": 2})
            THEME_SELECTION.pop(uid, None)
            THEME_PAIRS.pop(uid, None)
            await bot.answer_callback_query(c.id, text="Сохранено")
            await bot.send_message(
                chat_id,
                "Шаг 3 из 3. Выберите комфортную сложность:",
                reply_markup=onboarding_diff_keyboard(),
            )
            return
        if code == "skip":
            await api_patch_profile(uid, {"themes": [], "onboarding_step": 2})
            THEME_SELECTION.pop(uid, None)
            THEME_PAIRS.pop(uid, None)
            await bot.answer_callback_query(c.id, text="Ок")
            await bot.send_message(
                chat_id,
                "Шаг 3 из 3. Выберите комфортную сложность:",
                reply_markup=onboarding_diff_keyboard(),
            )
            return
        if code == "clear":
            THEME_SELECTION[uid] = set()
            await bot.answer_callback_query(c.id, text="Сброшено")
            try:
                await bot.edit_message_reply_markup(
                    chat_id, c.message.message_id, reply_markup=onboarding_themes_keyboard(uid)
                )
            except Exception as e:
                log.warning("edit_message_reply_markup themes: %s", e)
            return
        try:
            idx = int(code)
        except ValueError:
            await bot.answer_callback_query(c.id)
            return
        pairs = THEME_PAIRS.get(uid) or []
        if idx < 0 or idx >= len(pairs):
            await bot.answer_callback_query(c.id, text="Устарело — /start")
            return
        _, canon = pairs[idx]
        sel = THEME_SELECTION.setdefault(uid, set())
        if canon in sel:
            sel.remove(canon)
        else:
            sel.add(canon)
        await bot.answer_callback_query(c.id, text="Выбор обновлён")
        try:
            await bot.edit_message_reply_markup(
                chat_id, c.message.message_id, reply_markup=onboarding_themes_keyboard(uid)
            )
        except Exception as e:
            log.warning("edit_message_reply_markup themes toggle: %s", e)
        return

    if kind == "diff":
        if code not in ("easy", "medium", "hard"):
            await bot.answer_callback_query(c.id)
            return
        await api_patch_profile(
            uid,
            {"difficulty": code, "onboarding_done": True, "onboarding_step": 0},
        )
        await bot.answer_callback_query(c.id, text="Готово")
        await bot.send_message(chat_id, _ONBOARDING_COMPLETE)
        return

    await bot.answer_callback_query(c.id)


async def send_message_chunks(chat_id: int, text: str, **kwargs) -> None:
    """Split long text; inline keyboard (if any) attaches only to the last chunk."""
    reply_markup = kwargs.pop("reply_markup", None)
    t = text or ""
    if not t.strip():
        return
    remember_bot_outbound_text(chat_id, t)
    chunks: list[str] = []
    while t:
        chunks.append(t[:TG_MSG_LIMIT])
        t = t[TG_MSG_LIMIT:]
    for i, chunk in enumerate(chunks):
        extra = dict(kwargs)
        if i == len(chunks) - 1 and reply_markup is not None:
            extra["reply_markup"] = reply_markup
        await bot.send_message(chat_id, chunk, **extra)


@bot.message_handler(commands=["start"])
async def cmd_start(message):
    user = message.from_user
    if not user:
        return
    try:
        p = await api_profile(user.id)
    except httpx.HTTPError as e:
        await bot.send_message(message.chat.id, f"Не удалось связаться с API: {e!s}")
        return

    if not _profile_onboarding_complete(p):
        await resume_onboarding(message.chat.id, user.id)
        return

    await bot.send_message(message.chat.id, _START_ALREADY_DONE)


@bot.message_handler(commands=["setup"])
async def cmd_setup(message):
    """Сброс анкеты — нужен, если в БД уже стояло onboarding_done=true со старых версий."""
    user = message.from_user
    if not user:
        return
    try:
        await api_patch_profile(
            user.id,
            {
                "prefers_english": False,
                "prefers_russian": False,
                "themes": [],
                "difficulty": "medium",
                "onboarding_done": False,
                "onboarding_step": 0,
            },
        )
    except httpx.HTTPError as e:
        await bot.send_message(message.chat.id, f"Не удалось обновить профиль: {e!s}")
        return
    await resume_onboarding(message.chat.id, user.id)


@bot.message_handler(commands=["help"])
async def cmd_help(message):
    await bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(commands=["profile"])
async def cmd_profile(message):
    p = await api_profile(message.from_user.id)
    text = (
        f"Языки: EN={p['prefers_english']} RU={p['prefers_russian']}\n"
        f"Темы: {', '.join(p['themes']) or '—'}\n"
        f"Сложность: {p['difficulty']}\n"
        f"Выучено: {p['memorized_count']} • В работе: {p['learning_count']} • Повторы скоро: {p['due_review_count']}"
    )
    await bot.send_message(message.chat.id, text)


_NEXT_CARD_INVITE = (
    "\n\n———————————————\n"
    "Проверьте наизусть: нажмите «Проверка» под карточкой или отправьте /quiz — "
    "затем пришлите текст по памяти (или начните сообщение со «проверь» / «quiz»)."
)


async def send_poem_card_like_next(chat_id: int, poem: dict) -> None:
    """Тот же формат сообщения, что после /next (заголовок, язык, текст, кнопки)."""
    MEMORIZE_SLUG[chat_id] = poem["poem_slug"]
    keyboard = ReplyMarkup(poem["poem_slug"])
    catalog = (
        f"«{poem['title']}» — {poem['author']}\n"
        f"({poem['language']})\n\n"
        f"{poem['excerpt']}"
    )
    await send_message_chunks(chat_id, catalog + _NEXT_CARD_INVITE, reply_markup=keyboard)


async def deliver_repeat_graded_poem(chat_id: int, user_id: int) -> None:
    """Повторно показать стих, только что проверенный (как карточка /next)."""
    try:
        prof = await api_profile(user_id)
        if not _profile_onboarding_complete(prof):
            await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
            return
        slug = LAST_GRADED_SLUG.get(chat_id) or MEMORIZE_SLUG.get(chat_id)
        if not slug:
            await bot.send_message(
                chat_id,
                "Не удалось определить стих. Откройте рекомендацию через /next или пройдите проверку ещё раз.",
            )
            return
        poem = await api_poem_catalog_card(slug)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            await bot.send_message(chat_id, "Стих не найден в каталоге.")
            return
        await bot.send_message(chat_id, f"Не удалось загрузить стих: {e.response.text}")
        return
    except httpx.HTTPError as e:
        await bot.send_message(chat_id, f"Не удалось связаться с API: {e!s}")
        return

    await send_poem_card_like_next(chat_id, poem)


async def deliver_stats(chat_id: int, user_id: int) -> None:
    try:
        prof = await api_profile(user_id)
        if not _profile_onboarding_complete(prof):
            await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
            return
        data = await api_stats(user_id)
        summary = (data.get("summary_text") or "").strip()
        if not summary:
            summary = "Статистика пуста — по мере заучивания стихов здесь появятся детали."
        await send_message_chunks(chat_id, summary)
    except httpx.HTTPError as e:
        await bot.send_message(chat_id, f"Не удалось получить статистику: {e!s}")


async def deliver_next_recommendation(chat_id: int, user_id: int) -> None:
    try:
        prof = await api_profile(user_id)
        if not _profile_onboarding_complete(prof):
            await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
            return
        poem = await api_next(user_id)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
            return
        await bot.send_message(chat_id, f"Не удалось подобрать стих: {e.response.text}")
        return

    await send_poem_card_like_next(chat_id, poem)


@bot.message_handler(commands=["stats"])
async def cmd_stats(message):
    user = message.from_user
    if not user:
        return
    await deliver_stats(message.chat.id, user.id)


@bot.message_handler(commands=["review"])
async def cmd_review(message):
    d = await api_dashboard(message.from_user.id)
    upcoming = d.get("upcoming_reviews") or []
    lines = ["Ближайшие повторы (до 14 дней):"]
    if not upcoming:
        lines.append("Пока пусто — отличный повод нажать /next.")
    else:
        for row in upcoming[:10]:
            title = row.get("title", "?")
            slug = row.get("slug", "")
            due = row.get("due") or "скоро"
            lines.append(f"• {title} ({slug}) — {due}")
        if len(upcoming) > 10:
            lines.append(f"… и ещё {len(upcoming) - 10}.")
    await bot.send_message(message.chat.id, "\n".join(lines))


@bot.message_handler(commands=["next"])
async def cmd_next(message):
    user = message.from_user
    if not user:
        return
    await deliver_next_recommendation(message.chat.id, user.id)


async def activate_quiz_mode(
    chat_id: int,
    user_id: int,
    *,
    slug_from_card: str | None = None,
) -> None:
    """Включает режим как у /quiz: следующий текст оценивается по стиху из /next."""
    try:
        prof = await api_profile(user_id)
    except httpx.HTTPError as e:
        await bot.send_message(chat_id, f"Не удалось связаться с API: {e!s}")
        return
    if not _profile_onboarding_complete(prof):
        await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
        return
    slug = slug_from_card or MEMORIZE_SLUG.get(chat_id)
    if not slug:
        await bot.send_message(
            chat_id,
            "Сначала получите стих через /next. "
            "Проверка относится к стиху с последней рекомендации, а не к произведению из чата с коучем.",
        )
        return
    MEMORIZE_SLUG[chat_id] = slug
    QUIZ_PENDING[chat_id] = True
    label = slug
    try:
        label = _poem_label_from_api(await api_poem_meta(slug))
    except httpx.HTTPError:
        log.warning("api_poem_meta failed for slug=%s", slug)
    quiz_intro = (
        f"Режим проверки: {label}\n"
        "(стих из последней рекомендации /next)\n"
        "Следующее текстовое сообщение будет оценено как попытка вспомнить стих."
    )
    remember_bot_outbound_text(chat_id, quiz_intro)
    await bot.send_message(chat_id, quiz_intro)


@bot.message_handler(commands=["quiz"])
async def cmd_quiz(message):
    user = message.from_user
    if not user:
        return
    await activate_quiz_mode(message.chat.id, user.id)


def ReplyMarkup(slug: str):
    from telebot import types

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Принято — учить", callback_data=f"acc:{slug}"),
        types.InlineKeyboardButton("⏭ Пропуск", callback_data=f"skip:{slug}"),
    )
    kb.add(types.InlineKeyboardButton("📝 Проверка", callback_data=f"quiz:{slug}"))
    return kb


def QuizResultFollowupKeyboard():
    """После оценки проверки: статистика, следующая рекомендация, повтор карточки стиха."""
    from telebot import types

    kb = types.InlineKeyboardMarkup()
    kb.row(
        types.InlineKeyboardButton("📊 Статистика", callback_data="nav:stats"),
        types.InlineKeyboardButton("➡️ Следующий стих", callback_data="nav:next"),
    )
    kb.add(types.InlineKeyboardButton("🔁 Повторить стих", callback_data="nav:repeat"))
    return kb


@bot.callback_query_handler(func=lambda c: True)
async def on_callback(c):
    data = c.data or ""
    if data.startswith("ob:"):
        await onboarding_callback(c)
        return

    if data.startswith("nav:"):
        kind = data.split(":", 1)[1] if ":" in data else ""
        await bot.answer_callback_query(c.id)
        user = c.from_user
        if not user:
            return
        if kind == "stats":
            await deliver_stats(c.message.chat.id, user.id)
        elif kind == "next":
            await deliver_next_recommendation(c.message.chat.id, user.id)
        elif kind == "repeat":
            await deliver_repeat_graded_poem(c.message.chat.id, user.id)
        return

    parts = data.split(":", 1)
    if len(parts) != 2:
        await bot.answer_callback_query(c.id)
        return
    action, slug = parts
    if action == "quiz":
        await bot.answer_callback_query(c.id, text="Режим проверки")
        await activate_quiz_mode(c.message.chat.id, c.from_user.id, slug_from_card=slug)
        return

    outcome_map = {"acc": "accepted", "skip": "skipped", "done": "mastered"}
    outcome = outcome_map.get(action)
    if not outcome:
        await bot.answer_callback_query(c.id)
        return

    prof = await api_profile(c.from_user.id)
    if not _profile_onboarding_complete(prof):
        await bot.answer_callback_query(c.id, text="Сначала /start")
        return

    await api_outcome(c.from_user.id, slug, outcome)
    MEMORIZE_SLUG[c.message.chat.id] = slug

    hints = {
        "accepted": "Отлично, берём в работу — когда готовы, отправьте отрывок из памяти.",
        "skipped": "Записал пропуск — можно выбрать другое через /next.",
        "mastered": "Поздравляю! Я запланирую повтор через интервал spaced repetition.",
    }

    await bot.answer_callback_query(c.id, text="Записано")
    await bot.send_message(c.message.chat.id, hints[outcome])


@bot.message_handler(content_types=["voice", "audio", "video_note"])
async def on_voice(message):
    user = message.from_user
    try:
        if message.voice:
            fid = message.voice.file_id
            fname = "voice.oga"
        elif message.audio:
            fid = message.audio.file_id
            fname = message.audio.file_name or "audio.mp3"
        elif message.video_note:
            fid = message.video_note.file_id
            fname = "video_note.mp4"
        else:
            await bot.send_message(message.chat.id, "Не удалось прочитать аудиофайл.")
            return

        file_info = await bot.get_file(fid)
        audio_bytes = await bot.download_file(file_info.file_path)
        text = await transcribe_voice(audio_bytes, fname)
    except RuntimeError as e:
        detail = str(e) if str(e) not in ("speech_unavailable", "bad_response") else ""
        await bot.send_message(
            message.chat.id,
            "Расшифровка на сервере не удалась (Whisper/ffmpeg или нехватка RAM). "
            "Напишите текстом.\n"
            + (f"Детали: {detail[:600]}" if detail else ""),
        )
        return
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:500]
        await bot.send_message(
            message.chat.id,
            f"Backend ответил {e.response.status_code}. Проверьте логи API.\n{body}",
        )
        return
    except httpx.RequestError as e:
        await bot.send_message(
            message.chat.id,
            f"Не достучаться до API по {API_URL}: {e!s}\n"
            "Убедитесь, что backend запущен и в .env для бота указан верный API_URL "
            "(локально: http://127.0.0.1:8000; в Docker compose: http://api:8000).",
        )
        return
    except Exception as e:
        log.exception("voice handler")
        await bot.send_message(
            message.chat.id,
            f"Ошибка при расшифровке: {e!s}\nНапишите текстом или проверьте логи бота/API.",
        )
        return

    if not text.strip():
        await bot.send_message(message.chat.id, "Расшифровка пустая. Попробуйте ещё раз текстом.")
        return

    await bot.send_message(message.chat.id, f"_Текст:_ {text}", parse_mode="Markdown")
    await route_text(message.chat.id, user.id, text, display_name=user.full_name if user else None)


async def route_text(chat_id: int, user_id: int, text: str, display_name: str | None):
    try:
        prof = await api_profile(user_id)
    except httpx.HTTPError as e:
        log.warning("api_profile failed in route_text: %s", e)
        await bot.send_message(
            chat_id,
            f"Не удалось связаться с API ({API_URL}). Без профиля я не могу продолжить.\n{e!s}",
        )
        return

    if not _profile_onboarding_complete(prof):
        if await handle_onboarding_text(chat_id, user_id, text):
            return

    slug_for_check = _slug_for_keyword_check(chat_id)

    stripped = text.strip()
    lower = stripped.lower()

    should_quiz = slug_for_check and (
        QUIZ_PENDING.pop(chat_id, False)
        or lower.startswith("провер")
        or lower.startswith("quiz")
        or lower.startswith("цитат")
        or "процитируй" in lower
    )

    if should_quiz and slug_for_check:
        try:
            result = await api_check(user_id, slug_for_check, stripped)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                await bot.send_message(chat_id, "Сначала завершите профиль: /start или /setup")
                return
            raise
        fb = result["feedback"]
        score = result["score"]
        header = ""
        pt = (result.get("poem_title") or "").strip()
        pa = (result.get("poem_author") or "").strip()
        if pt:
            header = f"«{pt}» — {pa}\n\n" if pa else f"«{pt}»\n\n"
        LAST_GRADED_SLUG[chat_id] = slug_for_check
        quiz_body = f"{header}Оценка: {score:.2f}\n{fb}"
        remember_bot_outbound_text(chat_id, quiz_body)
        await bot.send_message(
            chat_id,
            quiz_body,
            reply_markup=QuizResultFollowupKeyboard(),
        )
        return

    try:
        last_ctx = LAST_BOT_OUTBOUND_TEXT.pop(chat_id, None)
        reply, hint = await api_chat(
            user_id,
            stripped,
            display_name=display_name,
            last_bot_message=last_ctx,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            await resume_onboarding(chat_id, user_id)
            return
        raise
    if hint:
        CHAT_POEM_HINT[chat_id] = hint
    await send_message_chunks(chat_id, reply)


@bot.message_handler(content_types=["text"])
async def on_text(message):
    await route_text(message.chat.id, message.from_user.id, message.text or "", message.from_user.full_name)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(bot.polling())


if __name__ == "__main__":
    main()
