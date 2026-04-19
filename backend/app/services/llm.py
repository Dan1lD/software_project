from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from openai import OpenAI

from app.config import get_settings


def _client() -> OpenAI:
    """Local SGLang OpenAI-compatible server — same pattern as openai.Client(...)."""
    s = get_settings()
    api_key = (s.llm_api_key or "None").strip() or "None"
    return OpenAI(base_url=s.llm_base_url, api_key=api_key)


async def chat_completion(
    *,
    system: str,
    user_messages: list[dict[str, str]],
    temperature: float = 0.75,
    top_p: float = 0.9,
    presence_penalty: float = 0.6,
    max_tokens: int | None = None,
) -> str:
    s = get_settings()

    def _run() -> str:
        kwargs: dict[str, Any] = dict(
            model=s.llm_model,
            messages=[{"role": "system", "content": system}, *user_messages],
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        completion = _client().chat.completions.create(**kwargs)
        return completion.choices[0].message.content or ""

    return await asyncio.to_thread(_run)


def extract_json_block(text: str) -> dict[str, Any] | None:
    """Parse trailing JSON block from model output if present."""
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        raw = fence.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    idx = text.rfind("{")
    if idx == -1:
        return None
    tail = text[idx:]
    try:
        return json.loads(tail)
    except json.JSONDecodeError:
        return None


async def judge_memorization(
    *, poem_title: str, poem_author: str, excerpt: str, recall: str
) -> tuple[float, str]:
    system = (
        "You compare the learner's recall ONLY to the REFERENCE_EXCERPT provided (from a fixed dataset). "
        "Do not judge against other lines you might know from real-world poetry — only the excerpt text given. "
        "In feedback, refer to the work by POEM_TITLE and POEM_AUTHOR (natural language), never by internal ids or slugs. "
        "Write feedback in the same language as learner_recall (Russian if the recall is Russian, English if English, etc.). "
        "Align the tone of feedback with the numeric score you output:\n"
        "- score >= 0.92: celebrate near-perfect recall; briefly congratulate; mention only trivial slips if any.\n"
        "- 0.72 <= score < 0.92: overall good but point out specific small inaccuracies "
        "(wrong words, omitted lines, shifted images, rhythm issues) compared to the excerpt.\n"
        "- score < 0.72: recall is weak; explicitly recommend studying this poem again before moving on; "
        "name 1–2 concrete gaps (missing stanzas, wrong gist, few lines recalled).\n"
        "Respond ONLY with compact JSON: {\"score\": number between 0 and 1, \"feedback\": string}. "
        "Score high if key lines or meaning match the excerpt; partial credit allowed."
    )
    user = json.dumps(
        {
            "poem_title": poem_title,
            "poem_author": poem_author,
            "reference_excerpt": excerpt,
            "learner_recall": recall,
        },
        ensure_ascii=False,
    )
    raw = await chat_completion(system=system, user_messages=[{"role": "user", "content": user}], temperature=0.2)
    try:
        data = json.loads(raw)
        score = float(data["score"])
        fb = str(data["feedback"])
        score = max(0.0, min(1.0, score))
        return score, fb
    except Exception:
        parsed = extract_json_block(raw) or {}
        try:
            score = float(parsed.get("score", 0.4))
            fb = str(parsed.get("feedback", "Keep practicing — focus on the opening lines."))
            return max(0.0, min(1.0, score)), fb
        except Exception:
            return 0.45, "Я оцениваю по смыслу — попробуйте процитировать начало или ключевые образы."
