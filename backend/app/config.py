from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/poetry.db"
    cors_origins: list[str] = ["*"]

    # OpenAI-compatible LLM (local SGLang — see Dockerfile.llm)
    llm_base_url: str = "http://127.0.0.1:3000/v1"
    llm_api_key: str = "None"
    llm_model: str = "t-tech/T-lite-it-2.1-FP8"

    # Optional: OpenAI API (legacy; voice uses local Whisper by default)
    openai_api_key: str | None = None

    # Local Whisper (faster-whisper) for /speech/transcribe
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_download_root: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
