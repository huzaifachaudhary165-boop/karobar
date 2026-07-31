"""One-time codes must never come back in an API response on a public host.

`/auth/otp/send` needs no authentication — it cannot, since the whole point is
that the person has lost their password. So a response that carries the code is
account takeover for any address someone can guess: ask for a reset code, read
it out of the JSON, post it to `/auth/reset-password`, and the account is theirs.

The live deployment had exactly that. `OTP_DEV_MODE` defaulted to on and
`ENVIRONMENT` defaulted to "development", so a host that simply did not set
either variable ran with the developer convenience switched on, facing the
internet. Neither default was wrong on its own; together they were.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


def settings_with(monkeypatch, **env) -> Settings:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file="")


def test_the_default_is_off(monkeypatch):
    """A convenience that is dangerous when forgotten has to be opt-in.

    The harness turns it on for every other test, so it has to be cleared here
    to see the default at all.
    """
    monkeypatch.delenv("OTP_DEV_MODE", raising=False)
    assert Settings(_env_file="").OTP_DEV_MODE is False


def test_a_serverless_host_never_exposes_codes_however_the_flag_is_set(monkeypatch):
    """The exact shape of the live failure: flag on, environment unset."""
    monkeypatch.setenv("VERCEL", "1")
    settings = settings_with(monkeypatch, OTP_DEV_MODE="true", ENVIRONMENT="development")

    assert settings.OTP_DEV_MODE is True, "the flag is honoured as configured"
    assert settings.expose_otp_codes is False, "but the codes are still withheld"


def test_production_never_exposes_codes(monkeypatch):
    settings = settings_with(monkeypatch, OTP_DEV_MODE="true", ENVIRONMENT="production")
    assert settings.expose_otp_codes is False


def test_local_development_still_gets_them(monkeypatch):
    """Otherwise nobody can sign in locally without a mail or SMS provider."""
    monkeypatch.delenv("VERCEL", raising=False)
    settings = settings_with(monkeypatch, OTP_DEV_MODE="true", ENVIRONMENT="development")
    assert settings.expose_otp_codes is True


def test_off_by_default_even_locally(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("OTP_DEV_MODE", raising=False)
    settings = settings_with(monkeypatch, ENVIRONMENT="development")
    assert settings.expose_otp_codes is False


# ── the warning that would have caught it ────────────────────────
def test_a_deployed_host_without_ENVIRONMENT_is_reported(monkeypatch):
    """Every other production check is gated on ENVIRONMENT, so a host that
    never set it skipped all of them — silently, while public."""
    monkeypatch.setenv("VERCEL", "1")
    warnings = settings_with(monkeypatch, ENVIRONMENT="development").sanity_check()
    joined = " ".join(warnings)

    assert "ENVIRONMENT" in joined
    assert "production" in joined


def test_dev_otp_on_a_deployed_host_is_reported(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    warnings = settings_with(
        monkeypatch, OTP_DEV_MODE="true", ENVIRONMENT="production"
    ).sanity_check()

    assert any("OTP_DEV_MODE" in w for w in warnings)


def test_a_correct_deployment_reports_nothing_about_this(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
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
        RATE_LIMIT_ENABLED="false",
    ).sanity_check()

    assert not any("ENVIRONMENT" in w or "OTP_DEV_MODE" in w for w in warnings), warnings


# ── end to end ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_reset_endpoint_withholds_the_code_on_a_public_host(
    client, account, monkeypatch
):
    """The whole attack, attempted against the running app."""
    from app.core.config import settings as live

    monkeypatch.setattr(live, "SERVERLESS", True)

    response = await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["debug_code"] is None, (
        "the code came back in the response — anyone knowing this email could "
        "reset the password with it"
    )


@pytest.mark.asyncio
async def test_a_stranger_cannot_reset_a_password_without_the_emailed_code(
    client, account, monkeypatch
):
    from app.core.config import settings as live

    monkeypatch.setattr(live, "SERVERLESS", True)

    await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )

    # Nothing in the response to work from, so all that is left is guessing.
    attempt = await client.post(
        "/auth/reset-password",
        json={
            "identifier": account["email"],
            "code": "000000",
            "new_password": "attacker-chosen-x1",
        },
    )
    assert attempt.status_code == 401

    # And the real password still works.
    signed_in = await client.post(
        "/auth/login",
        json={"identifier": account["email"], "password": account["password"]},
    )
    assert signed_in.status_code == 200
