"""Application settings — single source of truth, loaded from env/.env."""

from __future__ import annotations

import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # NoDecode is load-bearing. Without it pydantic-settings JSON-decodes any
    # complex-typed env var *before* validators run, so a perfectly reasonable
    # `CORS_ORIGINS=https://app.example.com` raises SettingsError at import and
    # takes the whole process down — which is exactly what happened on the first
    # production deploy. With it, the raw string reaches `_split_origins` below,
    # which accepts a bare URL, a comma-separated list, or a JSON array.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["*"]

    # ── Database ─────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./karobar.db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    # Seconds a single connect attempt may take. Deliberately short: a hanging
    # connect on a serverless host is killed by the platform, which reports only
    # FUNCTION_INVOCATION_FAILED and hides the cause entirely. Failing fast
    # produces a real exception instead.
    DB_CONNECT_TIMEOUT: int = 8
    # Connections a warm serverless instance may keep open to the transaction
    # pooler. Small on purpose: the win is not concurrency, it is not paying
    # ~2.9s of TLS and Postgres handshake on every single request. Set to 0 to
    # go back to a fresh connection per request.
    DB_SERVERLESS_POOL_SIZE: int = 1
    DB_SERVERLESS_MAX_OVERFLOW: int = 2
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
    # How long one assistant turn may spend before it must answer with
    # something. Retrying a throttled call is only worth it while the reply can
    # still be delivered — past that the host cuts the request off and the user
    # gets a dead spinner and a generic error instead of "try again in 12s".
    # Keep this comfortably under the host's own request ceiling (60s on Vercel).
    AI_REQUEST_BUDGET_SECONDS: float = 40.0
    # Groq's free tier costs nothing; the meter still counts tokens because the
    # per-minute budget is what actually runs out.
    AI_INPUT_COST_PER_MTOK: float = 0.0
    AI_OUTPUT_COST_PER_MTOK: float = 0.0

    # ── OTP / SMS ────────────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    # Returns the one-time code in the API response so a developer with no mail
    # or SMS provider can still sign in.
    #
    # Defaults to OFF. It used to default to ON, and ENVIRONMENT defaults to
    # "development", so a deployment that simply did not set either variable —
    # which is what the live one did — handed out password-reset codes to
    # anyone who asked for them. That is account takeover for any address
    # someone can guess, from an unauthenticated endpoint.
    #
    # A convenience that is dangerous when forgotten has to be opt-in.
    OTP_DEV_MODE: bool = False
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
        """Accepts every shape someone reasonably types into a hosting panel.

            https://app.example.com
            https://app.example.com, https://admin.example.com
            ["https://app.example.com"]
            *
        """
        if not isinstance(v, str):
            return v

        text = v.strip()
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # A malformed array is still better handled as a list of one
                # than by refusing to start.
                pass
        return [o.strip() for o in text.split(",") if o.strip()]

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _clean_database_url(cls, v: object) -> object:
        """Undo the two ways a connection string gets mistyped into a panel.

        A hosting panel has a key box and a value box. Pasting a whole `.env`
        line into the value box carries the `DATABASE_URL=` prefix along with
        it, and a copied line usually brings a trailing newline. Either one
        makes SQLAlchemy refuse to parse the URL at import, which takes the
        process down with no working route left to explain why — the failure
        this guards against cost a live deployment several hours.

        Only this exact prefix is removed. Anything else stays untouched, so a
        genuinely wrong URL still fails loudly instead of being papered over.
        """
        if not isinstance(v, str):
            return v

        text = v.strip().strip('"').strip("'").strip()
        if text.upper().startswith("DATABASE_URL="):
            text = text.split("=", 1)[1].strip()
        return text

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def expose_otp_codes(self) -> bool:
        """Whether a one-time code may be echoed back in an API response.

        Two conditions, because either one alone has already failed once. The
        flag can be left at a convenient default by accident, and ENVIRONMENT
        can be left unset on a host that is very much on the internet — the
        live deployment did both at the same time.

        A serverless host is by definition reachable by strangers, so it never
        gets the codes regardless of how the flag is set.
        """
        return self.OTP_DEV_MODE and not self.is_serverless and not self.is_production

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

        # The checks below are all gated on ENVIRONMENT, so a host that never
        # set it skips every one of them — while running with development
        # defaults on the public internet. That is exactly what happened, and
        # it is why this check has to come first and be unconditional.
        if self.is_serverless and not self.is_production:
            warnings.append(
                f"ENVIRONMENT is '{self.ENVIRONMENT}' on a deployed host. "
                "Development defaults are in force: interactive docs are "
                "exposed, and the schema is recreated on every cold start. "
                "Set ENVIRONMENT=production."
            )

        if self.OTP_DEV_MODE and self.is_serverless:
            warnings.append(
                "OTP_DEV_MODE is on for a deployed host. One-time codes would "
                "be returned in API responses, which is account takeover for "
                "any known address. They are suppressed anyway, but turn it off."
            )

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
