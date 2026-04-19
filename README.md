# Poetry — Conversational Recommender System

Telegram-first assistant that recommends classic poems in **English** and **Russian**, tracks memorization progress, spaced repetition-style reviews, and supports **text + voice**. Voice is transcribed on the backend with a **local Whisper** model ([faster-whisper](https://github.com/SYSTRAN/faster-whisper)); **ffmpeg** must be installed on the machine running the API (included in the Docker image).

Stack: **FastAPI** backend + **pyTelegramBotAPI** bot. LLM traffic goes to **local [SGLang](https://github.com/sgl-project/sglang)** (`lmsysorg/sglang:latest`, model `t-tech/T-lite-it-2.1-FP8`) via the OpenAI-compatible URL `http://127.0.0.1:3000/v1` (see `Dockerfile.llm` and `app/services/llm.py`).

## Requirements

- Python **3.11+** (3.12 recommended)
- Running **OpenAI-compatible inference** reachable from the backend (`LLM_BASE_URL`)
- Telegram **bot token** from BotFather
- **ffmpeg** on the API host (for decoding Telegram voice/audio); Docker image installs it automatically
- Disk space for Whisper weights (first request downloads the model; size depends on `WHISPER_MODEL_SIZE`, e.g. `base` ~140 MB)

## Quick start (local, two terminals)

### 1. Clone and virtualenv

```bash
git clone <your-repo-url>
cd project_for_sp
python -m venv .venv
```

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux / macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment

Copy `env.example` to `.env` at the project root and fill in values:

| Variable | Purpose |
|----------|---------|
| `BOT_TOKEN` | Telegram bot token |
| `API_URL` | Base URL of the API (bot process). Default `http://127.0.0.1:8000` |
| `LLM_BASE_URL` | OpenAI-compatible base URL (e.g. `http://127.0.0.1:3000/v1`) |
| `LLM_API_KEY` | Often `None` or empty for local servers |
| `LLM_MODEL` | Model id served by your inference stack |
| `WHISPER_MODEL_SIZE` | Local Whisper model: `tiny`, `base`, `small`, `medium`, `large-v3`, … |
| `WHISPER_DEVICE` | `cpu` (default) or `cuda` |
| `WHISPER_COMPUTE_TYPE` | e.g. `int8` on CPU, `float16` on GPU |
| `OPENAI_API_KEY` | *(Optional)* unused by default; reserved for other integrations |

The backend reads the same variables when using a shared `.env` in the working directory (see below). Put `.env` in `backend/` when running uvicorn from that folder, or export variables in the shell.

### 3. Start the API

From the `backend` folder so imports resolve as package `app`:

Windows (PowerShell, from project root after activating `.venv`):

```powershell
cd backend
$env:PYTHONPATH = "."
# Optional: copy ..\.env here or rely on env vars from the shell
..\.venv\Scripts\uvicorn.exe app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux / macOS:

```bash
cd backend
export PYTHONPATH=.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. Start the Telegram bot

From the **project root** (where `bot.py` lives), with the same virtualenv activated:

Windows:

```powershell
.\.venv\Scripts\python.exe bot.py
```

Linux / macOS:

```bash
./.venv/bin/python bot.py
```

Ensure `API_URL` in `.env` points at the running API (`http://127.0.0.1:8000` when local).

### Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Onboarding / greeting via LLM |
| `/next` | Next poem recommendation + inline outcomes |
| `/quiz` | Next text message scored as recall for the current poem slug |
| `/profile` | Learner snapshot (languages, themes, counts) |
| `/review` | Poems due for spaced-repetition review in the next ~14 days |
| `/help` | Short help |

Free-form chat goes through `POST /api/v1/chat`. Inline buttons record recommendation outcomes (`accepted` / `skipped` / `mastered`).

## Deployment with Docker Compose

From the project root (after creating `.env` from `env.example`):

```bash
docker compose build
docker compose up -d
```

Services:

- **`llm`** — **SGLang** (`Dockerfile.llm` → **`lmsysorg/sglang:latest` only**), serving **`t-tech/T-lite-it-2.1-FP8`** on port **3000** inside the container. Compose uses **`gpus: all`**, **`ipc: host`**, **`shm_size: 32g`**, and Hugging Face cache volume **`llm_hf_cache`**. First startup can take several minutes; the API waits until `/v1/models` responds.
- **`api`** — FastAPI on port **8000**. Default **`LLM_BASE_URL=http://llm:3000/v1`** so it reaches SGLang on the Docker network (equivalent to `openai.Client(base_url="http://127.0.0.1:3000/v1", api_key="None")` on the host — see `app/services/llm.py`).
- **`bot`** — uses `API_URL=http://api:8000` automatically.

From the host, the LLM is **`http://127.0.0.1:3000/v1`**. To bind your Windows Hugging Face cache like manual `docker run`, replace the `llm` service `volumes` entry with a bind mount to your path (or keep the named volume).

**Manual run (matches your flags):**

```bash
docker run --gpus all --shm-size 32g -p 3000:3000 \
  -v //c/Users/danil/.cache/huggingface:/root/.cache/huggingface \
  --ipc=host \
  lmsysorg/sglang:latest \
  python3 -m sglang.launch_server --model-path t-tech/T-lite-it-2.1-FP8 --host 0.0.0.0 --port 3000
```

Or build once from this repo and run the same command via the image tag **`poetry-sglang:latest`** (`docker compose build llm`).

### Poem catalogue (CSV)

On first startup (empty SQLite), the API seeds **100 English** poems from `backend/data/PoetryFoundationData.csv` and **100 Russian** from `backend/data/russianPoetryWithTheme.csv`. Texts are read from CSV only.

**Chat (`POST /api/v1/chat`):** the model returns **only JSON** with `reply_segments`: prose goes in `{"type":"text","content":"..."}` (no verses there), and poem bodies are requested only via `{"type":"poem","slug":"..."}` or `poem_full`. The API turns those into `[[poem:...]]` and `poem_placeholders.py` inserts text from SQLite — the user never sees LLM-generated poem lines.

To rebuild the catalogue after changing CSVs or limits, delete the SQLite file (e.g. `backend/data/poetry.db` locally or the `poetry_db` Docker volume) and restart the API.

Persisted SQLite data lives in the named volume `poetry_db` mounted at `/app/data` inside the API container. Downloaded Whisper weights are cached under `whisper_models` at `/root/.cache/huggingface` so restarts do not re-fetch the model.

## Project layout

```text
backend/app/          # FastAPI application (routes, models, services)
backend/data/*.csv    # Poem sources (100 EN + 100 RU rows loaded at seed)
bot.py                # Telegram client → REST API
requirements.txt      # Shared Python dependencies
Dockerfile            # API image
Dockerfile.bot        # Bot image
Dockerfile.llm        # SGLang (lmsysorg/sglang:latest) — t-tech/T-lite-it-2.1-FP8 on :3000
docker-compose.yml    # llm + api + bot
LICENSE               # MIT
```

## API overview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness |
| POST | `/api/v1/chat` | Conversational turn + implicit profile hints |
| GET | `/api/v1/learners/{telegram_user_id}` | Learner profile |
| GET | `/api/v1/learners/{telegram_user_id}/dashboard` | Dashboard aggregate |
| POST | `/api/v1/recommend/next` | Next recommendation (`telegram_user_id` query) |
| POST | `/api/v1/recommend/outcome` | Record outcome (`telegram_user_id` query + JSON body) |
| POST | `/api/v1/memorization/check` | Score recall vs excerpt (`telegram_user_id` query + JSON body) |
| POST | `/api/v1/speech/transcribe` | Multipart audio → text (local Whisper + ffmpeg) |

## License

MIT — see [LICENSE](LICENSE).
