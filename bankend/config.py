import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"), override=False)
load_dotenv(Path(__file__).with_name(".env.local"), override=True)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    ai_provider: str = os.getenv("AI_PROVIDER", "zhipu").strip().lower()
    zhipu_api_key: str | None = os.getenv("ZHIPU_API_KEY")
    zhipu_model: str = os.getenv("ZHIPU_MODEL", "glm-4.7-flash")
    zhipu_base_url: str = os.getenv(
        "ZHIPU_BASE_URL",
        "https://open.bigmodel.cn/api/paas/v4",
    ).rstrip("/")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv(
        "GEMINI_MODEL",
        "gemini-3.1-flash-lite",
    )
    max_history_messages: int = _env_int("MAX_HISTORY_MESSAGES", 24)
    max_output_tokens: int = _env_int("MAX_OUTPUT_TOKENS", 2048)
    connect_timeout_seconds: float = _env_float(
        "CONNECT_TIMEOUT_SECONDS",
        20.0,
    )
    idle_timeout_seconds: float = _env_float(
        "IDLE_TIMEOUT_SECONDS",
        30.0,
    )
    max_retries: int = _env_int("MAX_RETRIES", 2)
    max_concurrent_chats: int = _env_int("MAX_CONCURRENT_CHATS", 1)
    rate_limit_per_minute: int = _env_int("RATE_LIMIT_PER_MINUTE", 20)
    trust_proxy_headers: bool = _env_bool("TRUST_PROXY_HEADERS", False)
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    cors_origin_regex: str = os.getenv(
        "CORS_ORIGIN_REGEX",
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    )


settings = Settings()
