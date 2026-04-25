from __future__ import annotations

from app.routers import memorization as memorization_router_module
from app.routers import recommendations as recommendations_router_module
from app.routers import transcription as transcription_router_module
from fastapi.testclient import TestClient


def test_integration_recommendation_to_memorization_flow(
    client: TestClient, onboarded_user: int, monkeypatch
) -> None:
    async def _fake_chat_completion(**kwargs):  # noqa: ANN003
        return "A concise intro from model."

    async def _fake_judge_memorization(**kwargs):  # noqa: ANN003
        return 0.95, "Excellent recall."

    monkeypatch.setattr(recommendations_router_module, "chat_completion", _fake_chat_completion)
    monkeypatch.setattr(memorization_router_module, "judge_memorization", _fake_judge_memorization)

    stats_before = client.get(f"/api/v1/learners/{onboarded_user}/stats")
    assert stats_before.status_code == 200
    before_payload = stats_before.json()
    before_memorized = before_payload["learner"]["memorized_count"]

    recommend_resp = client.post("/api/v1/recommend/next", params={"telegram_user_id": onboarded_user})
    assert recommend_resp.status_code == 200
    rec = recommend_resp.json()
    assert rec["poem_slug"] == "seed-poem"
    assert rec["presentation"] == "A concise intro from model."

    outcome_resp = client.post(
        "/api/v1/recommend/outcome",
        params={"telegram_user_id": onboarded_user},
        json={"poem_slug": rec["poem_slug"], "outcome": "accepted"},
    )
    assert outcome_resp.status_code == 200
    assert outcome_resp.json() == {"status": "recorded"}

    check_resp = client.post(
        "/api/v1/memorization/check",
        params={"telegram_user_id": onboarded_user},
        json={"poem_slug": rec["poem_slug"], "recall_text": "A short full text for tests."},
    )
    assert check_resp.status_code == 200
    check_payload = check_resp.json()
    assert check_payload["score"] == 0.95
    assert check_payload["feedback"] == "Excellent recall."
    assert check_payload["next_review_at"] is not None

    stats_after = client.get(f"/api/v1/learners/{onboarded_user}/stats")
    assert stats_after.status_code == 200
    after_payload = stats_after.json()
    assert after_payload["learner"]["memorized_count"] >= before_memorized
    assert any(x["slug"] == "seed-poem" for x in after_payload["upcoming_reviews"])


def test_integration_onboarding_gate_then_enable(client: TestClient) -> None:
    user_id = 777001

    blocked_recommend = client.post("/api/v1/recommend/next", params={"telegram_user_id": user_id})
    assert blocked_recommend.status_code == 403
    assert blocked_recommend.json()["detail"] == "onboarding_required"

    blocked_mem = client.post(
        "/api/v1/memorization/check",
        params={"telegram_user_id": user_id},
        json={"poem_slug": "seed-poem", "recall_text": "test"},
    )
    assert blocked_mem.status_code == 403
    assert blocked_mem.json()["detail"] == "onboarding_required"

    patch_resp = client.patch(
        f"/api/v1/learners/{user_id}/profile",
        json={"onboarding_done": True, "prefers_english": True},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["onboarding_done"] is True


def test_integration_speech_failure_path(client: TestClient, monkeypatch) -> None:
    def _fake_transcribe_audio_file(path: str) -> str:
        raise RuntimeError("backend speech offline")

    monkeypatch.setattr(transcription_router_module, "transcribe_audio_file", _fake_transcribe_audio_file)

    response = client.post(
        "/api/v1/speech/transcribe",
        files={"audio": ("voice.oga", b"fake-binary-audio", "audio/ogg")},
    )
    assert response.status_code == 503
    assert "Speech transcription failed:" in response.json()["detail"]
