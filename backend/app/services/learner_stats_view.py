from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Learner
from app.schemas import LearnerStatsResponse
from app.services.recommendation import build_learner_stats_response


def format_learner_stats_ru(s: LearnerStatsResponse) -> str:
    lines: list[str] = []
    lines.append("📊 Статистика Poetry Pal")
    lines.append("")
    lines.append("Выученные произведения:")
    if s.memorized_works:
        for row in s.memorized_works:
            title = row.get("title", "?")
            author = (row.get("author") or "").strip()
            if author:
                lines.append(f"• «{title}» — {author}")
            else:
                lines.append(f"• «{title}»")
    else:
        lines.append("Пока нет — после успешных проверок стихи попадут сюда.")
    lines.append("")
    if s.upcoming_reviews:
        lines.append("Ближайшие повторы (до 14 дней):")
        for row in s.upcoming_reviews:
            title = row.get("title", "?")
            due_raw = row.get("due") or ""
            due_show = due_raw
            try:
                if due_raw:
                    dt = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
                    due_show = dt.strftime("%Y-%m-%d %H:%M UTC")
            except (TypeError, ValueError):
                pass
            lines.append(f"• «{title}» — {due_show}")
    else:
        lines.append("Ближайшие повторы (14 дней): пока пусто.")
    return "\n".join(lines)


async def learner_stats_reply_text(session: AsyncSession, learner: Learner) -> str:
    base = await build_learner_stats_response(session, learner=learner)
    return format_learner_stats_ru(base).strip()


async def learner_stats_response_with_summary(session: AsyncSession, learner: Learner) -> LearnerStatsResponse:
    base = await build_learner_stats_response(session, learner=learner)
    txt = format_learner_stats_ru(base).strip()
    return base.model_copy(update={"summary_text": txt})
