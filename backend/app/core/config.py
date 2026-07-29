"""Application settings — single source of truth, loaded from env/.env."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────
    APP_NAME: str = "Karobar"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── Security ─────────────────────────────────────────────────
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 60
    CORS_ORIGINS: list[str] = ["*"]

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./karobar.db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    # Force serverless connection behaviour on a host we do not auto-detect.
    SERVERLESS: bool = False

    # ── Supabase ─────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    # service_role, not the publishable key — uploads happen server-side.
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "karobar"

    # ── AI (Groq) ────────────────────────────────────────────────
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    # gpt-oss-120b and qwen3.6-27b both call tools reliably and read Roman Urdu.
    # llama-3.3-70b-versatile does NOT — it returns `tool_use_failed`.
    AI_MODEL: str = "openai/gpt-oss-120b"     # chat + OCR structuring
    AI_FAST_MODEL: str = "llama-3.1-8b-instant"  # summaries / short utility calls
    # Optional: the phone transcribes for free offline, this is the accurate
    # alternative when there is signal. turbo is ~4x cheaper in tokens than
    # large-v3 and good enough for a sentence of shop speech.
    AI_SPEECH_MODEL: str = "whisper-large-v3-turbo"
    AI_MAX_TOKENS: int = 4096
    AI_EFFORT: str = "medium"                 # low | medium | high
    AI_ENABLED: bool = True
    # Groq's free tier costs nothing; the meter still counts tokens because the
    # per-minute budget is what actually runs out.
    AI_INPUT_COST_PER_MTOK: float = 0.0
    AI_OUTPUT_COST_PER_MTOK: float = 0.0

    # ── OTP / SMS ────────────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_DEV_MODE: bool = True
    SMS_PROVIDER: str = ""
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""

    # ── Google / Gmail ───────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/integrations/gmail/callback"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Karobar"

    # ── WhatsApp ─────────────────────────────────────────────────
    WHATSAPP_ENABLED: bool = False
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = "karobar-verify-token"
    WHATSAPP_API_VERSION: str = "v21.0"

    # ── Storage ──────────────────────────────────────────────────
    STORAGE_BACKEND: Literal["local", "supabase", "s3"] = "local"
    STORAGE_DIR: str = "./storage"
    MAX_UPLOAD_MB: int = 15

    # ── Rate limiting ────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "300/minute"
    RATE_LIMIT_AUTH: str = "20/minute"
    RATE_LIMIT_AI: str = "60/minute"

    # ── Derived ──────────────────────────────────────────────────
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def storage_path(self) -> Path:
        """Where local uploads live. Reading this creates nothing.

        It used to `mkdir` here, which made merely *reading* a setting write to
        disk — and on a serverless host, where everything outside /tmp is
        read-only, that raised at import time and took the whole function down
        before a single request was served. The directory is now created by the
        code that actually writes a file.
        """
        if self.STORAGE_DIR.startswith("."):
            return (BASE_DIR / self.STORAGE_DIR).resolve()
        return Path(self.STORAGE_DIR)

    @property
    def ai_configured(self) -> bool:
        return self.AI_ENABLED and bool(self.GROQ_API_KEY)

    @property
    def is_serverless(self) -> bool:
        """True on Vercel/Lambda-style hosts, where each request may run in a
        fresh, short-lived process. Changes how the DB pool is configured."""
        return bool(
            os.getenv("VERCEL")
            or os.getenv("AWS_LAMBDA_FUNCTION_NAME")
            or os.getenv("FUNCTIONS_WORKER_RUNTIME")
            or self.SERVERLESS
        )

    @property
    def supabase_storage_ready(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_SERVICE_KEY and self.SUPABASE_BUCKET)

    def sanity_check(self) -> list[str]:
        """Returns a list of production-readiness warnings (empty == good)."""
        warnings: list[str] = []
        if self.is_production:
            if "change-me" in self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                warnings.append("SECRET_KEY is weak or default — set a 64-char random value.")
            if self.DEBUG:
                warnings.append("DEBUG is true in production.")
            if "*" in self.CORS_ORIGINS:
                warnings.append("CORS_ORIGINS allows '*' in production.")
            if self.is_sqlite:
                warnings.append("SQLite in production — point DATABASE_URL at Postgres/Supabase.")
            if self.OTP_DEV_MODE:
                warnings.append("OTP_DEV_MODE is on — OTPs are returned in API responses.")
            if self.STORAGE_BACKEND == "local":
                warnings.append(
                    "STORAGE_BACKEND is local — uploads live on the server's disk and are "
                    "lost if it is replaced. Point it at Supabase Storage."
                )
        if self.STORAGE_BACKEND == "supabase" and not self.supabase_storage_ready:
            warnings.append(
                "STORAGE_BACKEND is supabase but SUPABASE_URL/SUPABASE_SERVICE_KEY are "
                "not both set — falling back to local disk."
            )
        if self.is_serverless:
            if self.STORAGE_BACKEND == "local":
                warnings.append(
                    "Serverless host with local storage — uploads vanish between "
                    "invocations. Set STORAGE_BACKEND=supabase."
                )
            if "6543" not in self.DATABASE_URL and not self.is_sqlite:
                warnings.append(
                    "Serverless host not using the transaction pooler (port 6543) — "
                    "concurrent invocations will exhaust the database's connections."
                )
            if self.RATE_LIMIT_ENABLED:
                warnings.append(
                    "Rate limiting is in-process, so on a serverless host each "
                    "invocation counts separately and the limit is not enforced. "
                    "Put limits at the edge (or in Redis) instead."
                )
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
