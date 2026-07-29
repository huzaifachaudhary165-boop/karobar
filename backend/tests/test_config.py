"""Settings parsing.

Every one of these is a value a person plausibly types into a hosting panel.
Getting one wrong does not degrade a feature — pydantic-settings raises while
building the Settings object, which happens at import, so the whole process
fails to start. That is how the first production deploy went down: a perfectly
sensible `CORS_ORIGINS=https://karobar-e24a.vercel.app` was rejected before any
validator could see it.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def settings_with(monkeypatch, **env) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # _env_file="" so a developer's own .env cannot mask what is being tested.
    return Settings(_env_file="")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://app.example.com", ["https://app.example.com"]),
        ("  https://app.example.com  ", ["https://app.example.com"]),
        (
            "https://a.example.com,https://b.example.com",
            ["https://a.example.com", "https://b.example.com"],
        ),
        (
            "https://a.example.com, https://b.example.com",
            ["https://a.example.com", "https://b.example.com"],
        ),
        ('["https://a.example.com"]', ["https://a.example.com"]),
        ('["https://a.example.com","https://b.example.com"]',
         ["https://a.example.com", "https://b.example.com"]),
        ("*", ["*"]),
    ],
)
def test_cors_origins_accepts_every_shape_someone_types(monkeypatch, raw, expected):
    assert settings_with(monkeypatch, CORS_ORIGINS=raw).CORS_ORIGINS == expected


def test_a_malformed_json_array_still_starts(monkeypatch):
    """Refusing to boot over a stray bracket is a worse failure than a slightly
    wrong CORS list, which shows up as a browser error someone can act on."""
    parsed = settings_with(monkeypatch, CORS_ORIGINS='["https://a.example.com"').CORS_ORIGINS
    assert parsed, "must not raise, and must not be empty"


def test_trailing_comma_does_not_create_an_empty_origin(monkeypatch):
    # An empty string in this list would match nothing and confuse debugging.
    parsed = settings_with(monkeypatch, CORS_ORIGINS="https://a.example.com,").CORS_ORIGINS
    assert parsed == ["https://a.example.com"]


def test_production_flags_are_reported_when_left_at_development_values(monkeypatch):
    """The deploy checklist is enforced by code, not by remembering the docs."""
    warnings = settings_with(
        monkeypatch,
        ENVIRONMENT="production",
        DEBUG="true",
        OTP_DEV_MODE="true",
        CORS_ORIGINS="*",
    ).sanity_check()
    joined = " ".join(warnings)

    assert "DEBUG" in joined
    assert "OTP_DEV_MODE" in joined
    assert "CORS_ORIGINS" in joined


def test_a_correctly_configured_production_deploy_reports_nothing(monkeypatch):
    warnings = settings_with(
        monkeypatch,
        ENVIRONMENT="production",
        DEBUG="false",
        OTP_DEV_MODE="false",
        CORS_ORIGINS="https://app.example.com",
        SECRET_KEY="a" * 64,
        DATABASE_URL="postgresql+asyncpg://u:p@host.pooler.supabase.com:6543/postgres",
        STORAGE_BACKEND="supabase",
        SUPABASE_URL="https://x.supabase.co",
        SUPABASE_SERVICE_KEY="service-role",
    ).sanity_check()
    assert warnings == [], f"unexpected warnings: {warnings}"


POOLER = "postgresql+asyncpg://u:p@aws-1-ap-south-1.pooler.supabase.com:6543/postgres"


@pytest.mark.parametrize(
    "raw",
    [
        POOLER,
        f"DATABASE_URL={POOLER}",          # whole .env line pasted into the value box
        f"database_url={POOLER}",
        f"  DATABASE_URL={POOLER}  ",
        f"{POOLER}\n",                     # trailing newline from a copied line
        f'"{POOLER}"',                     # quotes carried over from the .env file
        f"'{POOLER}'",
    ],
)
def test_database_url_survives_the_usual_paste_mistakes(monkeypatch, raw):
    """A hosting panel has a key box and a value box. Putting the whole
    `KEY=value` line in the value box is a normal mistake, and it used to take
    the entire deployment down at import with no route left to explain why."""
    assert settings_with(monkeypatch, DATABASE_URL=raw).DATABASE_URL == POOLER


def test_a_genuinely_wrong_database_url_is_not_papered_over(monkeypatch):
    """Cleaning is limited to the known paste mistakes. A real typo must still
    reach SQLAlchemy and fail loudly rather than be silently rewritten."""
    assert settings_with(monkeypatch, DATABASE_URL="postgres@@broken").DATABASE_URL == (
        "postgres@@broken"
    )


def test_cleaned_database_url_still_connects_to_a_real_engine(monkeypatch):
    """The point of cleaning is that SQLAlchemy can parse the result — assert
    on that directly, not just on string equality."""
    from sqlalchemy.engine import make_url

    cleaned = settings_with(monkeypatch, DATABASE_URL=f"DATABASE_URL={POOLER}\n").DATABASE_URL
    url = make_url(cleaned)

    assert url.drivername == "postgresql+asyncpg"
    assert url.port == 6543


def test_reading_the_storage_path_creates_nothing(monkeypatch, tmp_path):
    """A property that writes to disk is what made the app unable to boot on a
    read-only filesystem."""
    target = tmp_path / "not-created-yet"
    resolved = settings_with(monkeypatch, STORAGE_DIR=str(target)).storage_path

    assert resolved == target
    assert not target.exists()
