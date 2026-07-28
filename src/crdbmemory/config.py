import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str | None = os.getenv("DATABASE_URL")
    database_url_local: str | None = os.getenv("DATABASE_URL_LOCAL")

    # Chat/reasoning (extract + contradiction judging) — Claude, via the
    # Anthropic SDK's own credential resolution (ANTHROPIC_API_KEY /
    # ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile). No key stored here.
    chat_model: str = os.getenv("CHAT_MODEL", "claude-opus-5")

    # Embeddings — Claude has no embeddings endpoint, so this uses Gemini
    # (also within the Claude/Gemini/Grok provider set).
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    embed_model: str = os.getenv("EMBED_MODEL", "gemini-embedding-001")
    embed_dim: int = int(os.getenv("EMBED_DIM", "1024"))

    # "live" for real Claude + Gemini calls, "mock" for deterministic offline dev/CI
    llm_backend: str = os.getenv("LLM_BACKEND", "mock")

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    s3_archive_bucket: str | None = os.getenv("S3_ARCHIVE_BUCKET") or None


settings = Settings()
