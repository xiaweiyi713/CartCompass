from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


REPO_DIR = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_DIR / "server"

load_dotenv(SERVER_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return [item.strip() for item in value.split(",") if item.strip()]

DB_PATH = Path(os.getenv("SHOPGUIDE_DB", SERVER_DIR / "storage" / "shopguide.sqlite3"))
STORAGE_DIR = DB_PATH.parent
STATIC_DIR = Path(os.getenv("SHOPGUIDE_STATIC_DIR", SERVER_DIR / "static"))
PRODUCT_IMAGE_DIR = STATIC_DIR / "product_images"

VECTOR_STORE_BACKEND = os.getenv("VECTOR_STORE_BACKEND", "sqlite").strip().lower()
CHROMA_PATH = Path(os.getenv("CHROMA_PATH", SERVER_DIR / "storage" / "chroma"))
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "shopguide_products")

# CORS allowlist. Default "*" keeps local demos and the native iOS client
# friction-free; set a comma-separated whitelist (e.g.
# "https://app.example.com,https://admin.example.com") to lock it down for
# a public deployment.
CORS_ALLOW_ORIGINS = _env_list("CORS_ALLOW_ORIGINS", ["*"])

ARK_API_KEY = os.getenv("ARK_API_KEY", "")
ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-0-lite-260428")
ARK_TIMEOUT_SECONDS = float(os.getenv("ARK_TIMEOUT_SECONDS", "8"))

LLM_DEFAULT_PROVIDER = os.getenv("LLM_DEFAULT_PROVIDER", "ark")
LLM_DEFAULT_TIMEOUT_SECONDS = float(os.getenv("LLM_DEFAULT_TIMEOUT_SECONDS", str(ARK_TIMEOUT_SECONDS)))
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

TEXT_EMBEDDING_BASE_URL = os.getenv("TEXT_EMBEDDING_BASE_URL", ARK_BASE_URL)
TEXT_EMBEDDING_MODEL = os.getenv("TEXT_EMBEDDING_MODEL", "")
TEXT_EMBEDDING_API_KEY = os.getenv("TEXT_EMBEDDING_API_KEY") or ARK_API_KEY
TEXT_EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("TEXT_EMBEDDING_TIMEOUT_SECONDS", "8"))
TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT = _env_bool("TEXT_EMBEDDING_ALLOW_REQUEST_UPSERT", False)
TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP = _env_bool("TEXT_EMBEDDING_PRECOMPUTE_ON_STARTUP", False)
TEXT_EMBEDDING_PRECOMPUTE_LIMIT = _env_int("TEXT_EMBEDDING_PRECOMPUTE_LIMIT", 0)

SESSION_TTL_SECONDS = _env_int("SESSION_TTL_SECONDS", 60 * 60 * 6)
SESSION_MAX_ENTRIES = _env_int("SESSION_MAX_ENTRIES", 500)

VISION_UNDERSTANDING_BASE_URL = os.getenv("VISION_UNDERSTANDING_BASE_URL", ARK_BASE_URL)
VISION_UNDERSTANDING_MODEL = os.getenv("VISION_UNDERSTANDING_MODEL", "doubao-seed-2-0-lite-260428")
VISION_UNDERSTANDING_API_KEY = os.getenv("VISION_UNDERSTANDING_API_KEY") or ARK_API_KEY
VISION_UNDERSTANDING_TIMEOUT_SECONDS = float(os.getenv("VISION_UNDERSTANDING_TIMEOUT_SECONDS", "12"))
VISION_UNDERSTANDING_IMAGE_DETAIL = os.getenv("VISION_UNDERSTANDING_IMAGE_DETAIL", "low")
VISION_UNDERSTANDING_MAX_IMAGE_SIDE = int(os.getenv("VISION_UNDERSTANDING_MAX_IMAGE_SIDE", "768"))
VISION_UNDERSTANDING_MAX_TOKENS = int(os.getenv("VISION_UNDERSTANDING_MAX_TOKENS", "240"))
VISION_UNDERSTANDING_JSON_MODE = _env_bool("VISION_UNDERSTANDING_JSON_MODE", False)
