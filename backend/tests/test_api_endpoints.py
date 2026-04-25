from __future__ import annotations

from fastapi.testclient import TestClient

from app.routers import chat as chat_router_module
from app.routers import memorization as memorization_router_module
from app.routers import recommendations as recommendations_router_module
from app.routers import transcription as transcription_router_module


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_learners_endpoints(client: TestClient) -> None:
    user_id = 42

    get_resp = client.get(f"/api/v1/learners/{user_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["telegram_user_id"] == user_id
    assert get_resp.json()["onboarding_done"] is False

    patch_resp = client.patch(
        f"/api/v1/learners/{user_id}/profile",
        json={
            "prefers_english": True,
            "themes": ["nature", "friendship"],
            "difficulty": "medium",
            "onboarding_done": True,
        },
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["prefers_english"] is True
    assert patched["themes"] == ["nature", "friendship"]
    assert patched["difficulty"] == "medium"
    assert patched["onboarding_done"] is True

    dashboard_resp = client.get(f"/api/v1/learners/{user_id}/dashboard")
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert "learner" in dashboard
    assert "recent_attempts" in dashboard
    assert "upcoming_reviews" in dashboard

    stats_resp = client.get(f"/api/v1/learners/{user_id}/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert "learner" in stats
    assert "memorized_works" in stats
    assert "upcoming_reviews" in stats
    assert "summary_text" in stats


def test_chat_endpoint_requires_onboarding(client: TestClient) -> None:
    payload = {"telegram_user_id": 1001, "message": "hello"}
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 403
    assert response.json()["detail"] == "onboarding_required"


def test_chat_endpoint_success(client: TestClient, onboarded_user: int, monkeypatch) -> None:
    async def _fake_handle_user_message(session, learner, text, last_bot_message):  # noqa: ANN001
        return "Bot reply", {"x": "y"}, None

    async def _fake_apply_profile_updates(session, learner, meta):  # noqa: ANN001
        return None

    def _fake_extract_recommend_slug(meta, reply):  # noqa: ANN001
        return "seed-poem"

    monkeypatch.setattr(chat_router_module, "handle_user_message", _fake_handle_user_message)
    monkeypatch.setattr(chat_router_module, "apply_profile_updates", _fake_apply_profile_updates)
    monkeypatch.setattr(chat_router_module, "extract_recommend_slug", _fake_extract_recommend_slug)

    response = client.post(
        "/api/v1/chat",
        json={"telegram_user_id": onboarded_user, "message": "Recommend me a poem"},
    )
    assert response.status_code == 200
    assert response.json() == {"reply": "Bot reply", "poem_slug_hint": "seed-poem"}


def test_recommendation_endpoints(client: TestClient, onboarded_user: int, monkeypatch) -> None:
    async def _fake_chat_completion(**kwargs):  # noqa: ANN003
        return "A short prose introduction."

    monkeypatch.setattr(recommendations_router_module, "chat_completion", _fake_chat_completion)

    card_resp = client.get("/api/v1/recommend/card", params={"poem_slug": "seed-poem"})
    assert card_resp.status_code == 200
    assert card_resp.json()["poem_slug"] == "seed-poem"

    next_resp = client.post("/api/v1/recommend/next", params={"telegram_user_id": onboarded_user})
    assert next_resp.status_code == 200
    next_payload = next_resp.json()
    assert next_payload["poem_slug"] == "seed-poem"
    assert next_payload["presentation"] == "A short prose introduction."

    outcome_resp = client.post(
        "/api/v1/recommend/outcome",
        params={"telegram_user_id": onboarded_user},
        json={"poem_slug": "seed-poem", "outcome": "accepted"},
    )
    assert outcome_resp.status_code == 200
    assert outcome_resp.json() == {"status": "recorded"}


def test_memorization_endpoints(client: TestClient, onboarded_user: int, monkeypatch) -> None:
    async def _fake_judge_memorization(**kwargs):  # noqa: ANN003
        return 0.9, "Good recall."

    monkeypatch.setattr(memorization_router_module, "judge_memorization", _fake_judge_memorization)

    poem_resp = client.get("/api/v1/memorization/poem", params={"poem_slug": "seed-poem"})
    assert poem_resp.status_code == 200
    assert poem_resp.json()["slug"] == "seed-poem"

    check_resp = client.post(
        "/api/v1/memorization/check",
        params={"telegram_user_id": onboarded_user},
        json={"poem_slug": "seed-poem", "recall_text": "A short full text for tests."},
    )
    assert check_resp.status_code == 200
    payload = check_resp.json()
    assert payload["poem_slug"] == "seed-poem"
    assert payload["score"] == 0.9
    assert payload["feedback"] == "Good recall."
    assert payload["next_review_at"] is not None


def test_speech_transcribe_endpoint(client: TestClient, monkeypatch) -> None:
    def _fake_transcribe_audio_file(path: str) -> str:
        assert path
        return "transcribed speech"

    monkeypatch.setattr(transcription_router_module, "transcribe_audio_file", _fake_transcribe_audio_file)

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"audio": ("voice.oga", b"fake-binary-audio", "audio/ogg")},
    )
    assert response.status_code == 200
    assert response.json() == {"text": "transcribed speech"}


def test_speech_transcribe_empty_upload(client: TestClient) -> None:
    response = client.post(
        "/api/v1/speech/transcribe",
        files={"audio": ("voice.oga", b"", "audio/ogg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Empty upload"


def test_recommend_next_requires_onboarding(client: TestClient) -> None:
    response = client.post("/api/v1/recommend/next", params={"telegram_user_id": 999})
    assert response.status_code == 403
    assert response.json()["detail"] == "onboarding_required"


def test_memorization_check_requires_onboarding(client: TestClient) -> None:
    response = client.post(
        "/api/v1/memorization/check",
        params={"telegram_user_id": 1002},
        json={"poem_slug": "seed-poem", "recall_text": "test"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "onboarding_required"


def test_memorization_poem_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/memorization/poem", params={"poem_slug": "unknown"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown poem slug"


def test_recommend_card_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/recommend/card", params={"poem_slug": "unknown"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown poem slug"
