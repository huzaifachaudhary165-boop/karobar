"""Google sign-in token verification.

A Google ID token proves who someone is *to a particular app*. Anybody can
register a Google app and mint valid, correctly-signed tokens for their own
users, so a good signature by itself proves nothing to us — it is the `aud`
claim, checked against our own client id, that turns the token into evidence.

These tests exist because the audience check used to be conditional on
GOOGLE_CLIENT_ID being set, and the deployed server had it unset.
"""

from __future__ import annotations

import pytest

from app.core.errors import AuthenticationError
from app.services.auth_service import AuthService

OUR_CLIENT = "ours.apps.googleusercontent.com"
SOMEONE_ELSES_CLIENT = "attacker.apps.googleusercontent.com"


def auth_service(monkeypatch, client_id: str) -> AuthService:
    """An AuthService with no database — none of these paths reach one."""
    monkeypatch.setattr("app.services.auth_service.settings.GOOGLE_CLIENT_ID", client_id)
    # google-auth would verify the signature locally and reject the fake tokens
    # before the audience check runs; forcing the tokeninfo path is what puts
    # that check under test.
    monkeypatch.setitem(__import__("sys").modules, "google.oauth2", None)
    return AuthService(db=None)  # type: ignore[arg-type]


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def patch_tokeninfo(monkeypatch, response: FakeResponse) -> None:
    """Stand in for Google's tokeninfo endpoint."""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_args, **_kwargs):
            return response

    monkeypatch.setattr("app.services.auth_service.httpx.AsyncClient", lambda **_: FakeClient())


@pytest.mark.asyncio
async def test_an_unconfigured_server_refuses_google_sign_in(monkeypatch):
    """The dangerous case. With no client id there is nothing to match `aud`
    against, so accepting the token would let a token minted by any Google app
    log into — or silently create — the account holding that email."""
    patch_tokeninfo(
        monkeypatch,
        FakeResponse(200, {"sub": "1", "email": "victim@gmail.com", "aud": SOMEONE_ELSES_CLIENT}),
    )
    service = auth_service(monkeypatch, "")

    with pytest.raises(AuthenticationError) as exc:
        await service._verify_google_token("a-token-from-some-other-app")

    assert "not configured" in str(exc.value)


@pytest.mark.asyncio
async def test_a_token_issued_for_another_app_is_refused(monkeypatch):
    patch_tokeninfo(
        monkeypatch,
        FakeResponse(200, {"sub": "1", "email": "victim@gmail.com", "aud": SOMEONE_ELSES_CLIENT}),
    )
    service = auth_service(monkeypatch, OUR_CLIENT)

    with pytest.raises(AuthenticationError) as exc:
        await service._verify_google_token("a-token-from-some-other-app")

    assert "another app" in str(exc.value)


@pytest.mark.asyncio
async def test_a_token_issued_for_us_is_accepted(monkeypatch):
    patch_tokeninfo(
        monkeypatch,
        FakeResponse(200, {"sub": "1", "email": "owner@gmail.com", "aud": OUR_CLIENT}),
    )
    service = auth_service(monkeypatch, OUR_CLIENT)

    claims = await service._verify_google_token("a-token-issued-for-karobar")

    assert claims["email"] == "owner@gmail.com"


@pytest.mark.asyncio
async def test_a_token_google_itself_rejects_is_refused(monkeypatch):
    patch_tokeninfo(monkeypatch, FakeResponse(400, {"error": "invalid_token"}))
    service = auth_service(monkeypatch, OUR_CLIENT)

    with pytest.raises(AuthenticationError) as exc:
        await service._verify_google_token("expired-or-forged")

    assert "could not be verified" in str(exc.value)


@pytest.mark.asyncio
async def test_the_endpoint_does_not_leak_which_check_failed(client, monkeypatch):
    """A caller learns that sign-in failed, never whether the server is
    misconfigured, the token expired, or it belonged to another app."""
    response = await client.post("/auth/google", json={"id_token": "x" * 60})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
