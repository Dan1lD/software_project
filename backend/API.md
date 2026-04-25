# Backend API Contract (FastAPI)

Base URL (local): `http://127.0.0.1:8000`  
API prefix: `/api/v1`  
Swagger: `http://127.0.0.1:8000/docs`

This document is generated from backend code and describes full input/output contracts using Python type notation.

---

## 1) Common Conventions

- **Content-Type (default):** `application/json`
- **Date-time format:** ISO 8601 string, e.g. `"2026-04-27T09:00:00+00:00"`
- **Errors (FastAPI):** `{"detail": <str | dict | list>}`
- Some endpoints require completed onboarding and may return `403` with `detail: "onboarding_required"`.

---

## 2) Shared Schemas (Python Types)
```

### 2.1 `LearnerPublic`

```python
class LearnerPublic(TypedDict):
    telegram_user_id: int
    display_name: str | None
    prefers_english: bool
    prefers_russian: bool
    themes: list[str]
    difficulty: str  # usually "easy" | "medium" | "hard"
    notes: str | None
    onboarding_done: bool
    onboarding_step: int
    memorized_count: int
    learning_count: int
    due_review_count: int
```

### 2.2 `LearnerProfilePatch` (request body)

All fields are optional; only provided fields are applied.

```python
class LearnerProfilePatch(TypedDict, total=False):
    prefers_english: bool | None
    prefers_russian: bool | None
    themes: list[str] | None
    difficulty: str | None  # applied only for "easy" | "medium" | "hard"
    notes: str | None
    onboarding_done: bool | None
    onboarding_step: int | None
```

### 2.3 `ChatRequest`

```python
class ChatRequest(TypedDict):
    telegram_user_id: int
    display_name: NotRequired[str | None]
    message: str  # min length 1, max length 12000
    last_bot_message: NotRequired[str | None]  # max length 14000
```

### 2.4 `ChatResponse`

```python
class ChatResponse(TypedDict):
    reply: str
    poem_slug_hint: str | None
```

### 2.5 `NextRecommendationResponse`

```python
class NextRecommendationResponse(TypedDict):
    poem_slug: str
    title: str
    author: str
    language: str  # "en" | "ru"
    excerpt: str
    presentation: str
```

### 2.6 `PoemCatalogCard`

```python
class PoemCatalogCard(TypedDict):
    poem_slug: str
    title: str
    author: str
    language: str  # "en" | "ru"
    excerpt: str
```

### 2.7 `OutcomeRequest`

```python
class OutcomeRequest(TypedDict):
    poem_slug: str
    outcome: Literal["accepted", "skipped", "mastered"]
```

### 2.8 `PoemMetaResponse`

```python
class PoemMetaResponse(TypedDict):
    slug: str
    title: str
    author: str
    language: str  # "en" | "ru"
```

### 2.9 `MemorizationRequest`

```python
class MemorizationRequest(TypedDict):
    poem_slug: str
    recall_text: str  # min length 1, max length 12000
```

### 2.10 `MemorizationResponse`

```python
class MemorizationResponse(TypedDict):
    score: float
    feedback: str
    next_review_at: str | None  # ISO datetime string
    poem_title: str
    poem_author: str
    poem_slug: str
```

### 2.11 `LearnerDashboard`

```python
class LearnerDashboardRecentAttemptItem(TypedDict):
    poem: str
    score: float


class LearnerDashboardUpcomingReviewItem(TypedDict):
    slug: str
    title: str
    due: str | None  # ISO datetime string


class LearnerDashboard(TypedDict):
    learner: LearnerPublic
    recent_attempts: list[LearnerDashboardRecentAttemptItem]
    upcoming_reviews: list[LearnerDashboardUpcomingReviewItem]
```

### 2.12 `LearnerStatsResponse`

```python
class LearnerStatsMemorizedWorkItem(TypedDict):
    slug: str
    title: str
    author: str


class LearnerStatsUpcomingReviewItem(TypedDict):
    slug: str
    title: str
    due: str | None  # ISO datetime string


class LearnerStatsResponse(TypedDict):
    learner: LearnerPublic
    memorized_works: list[LearnerStatsMemorizedWorkItem]
    upcoming_reviews: list[LearnerStatsUpcomingReviewItem]
    summary_text: str
```

---

## 3) Endpoints

### 3.1 GET `/health`

**Description:** service liveness check.

**Request:** no params, no body.

**Response 200**

```json
{
  "status": "ok"
}
```

```python
class HealthResponse(TypedDict):
    status: str
```

---

### 3.2 POST `/api/v1/chat`

**Description:** one conversational turn with assistant.

**Request body:** `ChatRequest`  
**Response 200:** `ChatResponse`

**Possible errors**

- `403` with `detail: "onboarding_required"`
- `422` validation error

---

### 3.3 GET `/api/v1/learners/{telegram_user_id}`

```python
class LearnerPathParams(TypedDict):
    telegram_user_id: int
```

**Response 200:** `LearnerPublic`

**Possible errors**

- `422` validation error

---

### 3.4 PATCH `/api/v1/learners/{telegram_user_id}/profile`

```python
class LearnerPathParams(TypedDict):
    telegram_user_id: int
```

**Request body:** `LearnerProfilePatch`  
**Response 200:** `LearnerPublic`

**Notes**

- `difficulty` is updated only for values: `"easy"`, `"medium"`, `"hard"`.

**Possible errors**

- `422` validation error

---

### 3.5 GET `/api/v1/learners/{telegram_user_id}/dashboard`

```python
class LearnerPathParams(TypedDict):
    telegram_user_id: int
```

**Response 200:** `LearnerDashboard`

**Possible errors**

- `422` validation error

---

### 3.6 GET `/api/v1/learners/{telegram_user_id}/stats`

```python
class LearnerPathParams(TypedDict):
    telegram_user_id: int
```

**Response 200:** `LearnerStatsResponse`

**Possible errors**

- `422` validation error

---

### 3.7 POST `/api/v1/recommend/next?telegram_user_id={id}`

```python
class TelegramUserQuery(TypedDict):
    telegram_user_id: int
```

**Response 200:** `NextRecommendationResponse`

**Possible errors**

- `403` with `detail: "onboarding_required"`
- `404` with `detail: "No suitable poem found — adjust preferences."`
- `422` validation error

---

### 3.8 POST `/api/v1/recommend/outcome?telegram_user_id={id}`

```python
class TelegramUserQuery(TypedDict):
    telegram_user_id: int
```

**Request body:** `OutcomeRequest`

**Response 200**

```json
{
  "status": "recorded"
}
```

```python
class OutcomeResponse(TypedDict):
    status: str
```

**Possible errors**

- `403` with `detail: "onboarding_required"`
- `422` validation error

---

### 3.9 GET `/api/v1/recommend/card?poem_slug={slug}`

```python
class PoemSlugQuery(TypedDict):
    poem_slug: str  # min length 1, max length 256
```

**Response 200:** `PoemCatalogCard`

**Possible errors**

- `404` with `detail: "Unknown poem slug"`
- `422` validation error

---

### 3.10 GET `/api/v1/memorization/poem?poem_slug={slug}`

```python
class PoemSlugQuery(TypedDict):
    poem_slug: str  # min length 1, max length 256
```

**Response 200:** `PoemMetaResponse`

**Possible errors**

- `404` with `detail: "Unknown poem slug"`
- `422` validation error

---

### 3.11 POST `/api/v1/memorization/check?telegram_user_id={id}`

```python
class TelegramUserQuery(TypedDict):
    telegram_user_id: int
```

**Request body:** `MemorizationRequest`  
**Response 200:** `MemorizationResponse`

**Possible errors**

- `403` with `detail: "onboarding_required"`
- `404` with `detail: "Unknown poem slug"`
- `422` validation error

---

### 3.12 POST `/api/v1/speech/transcribe`

**Description:** transcribes uploaded audio via local Whisper.

**Request content-type:** `multipart/form-data`

```python
class SpeechTranscribeFormData(TypedDict):
    audio: bytes  # uploaded file content
```

**Response 200**

```json
{
  "text": "recognized text"
}
```

```python
class SpeechTranscribeResponse(TypedDict):
    text: str
```

**Possible errors**

- `400` with `detail: "Empty upload"`
- `503` with `detail: "Speech transcription failed: ..."`
- `422` validation error

---

## 4) Complete Route List

- `GET /health`
- `POST /api/v1/chat`
- `GET /api/v1/learners/{telegram_user_id}`
- `PATCH /api/v1/learners/{telegram_user_id}/profile`
- `GET /api/v1/learners/{telegram_user_id}/dashboard`
- `GET /api/v1/learners/{telegram_user_id}/stats`
- `POST /api/v1/recommend/next`
- `POST /api/v1/recommend/outcome`
- `GET /api/v1/recommend/card`
- `GET /api/v1/memorization/poem`
- `POST /api/v1/memorization/check`
- `POST /api/v1/speech/transcribe`
