"""Forgot-password flow.

The failure this guards against is not a crash: it is a shopkeeper typing an
address they never registered, being told a code is on its way, and then
watching an inbox that will stay empty forever with nothing on screen to
explain why. Every test here is about the app telling the truth early enough
for the person to act on it.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_reset_for_an_unknown_address_says_so_immediately(client):
    response = await client.post(
        "/auth/otp/send",
        json={"identifier": "nobody-here@testshop.pk", "purpose": "reset_password"},
    )

    assert response.status_code == 404, response.text
    message = response.json()["error"]["message"]
    assert "No account" in message
    # It must also point somewhere useful, not just refuse.
    assert "create a new account" in message


@pytest.mark.asyncio
async def test_reset_for_a_real_account_sends_a_code(client, account):
    response = await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["debug_code"], "dev mode must return a usable code"


@pytest.mark.asyncio
async def test_the_whole_reset_round_trip(client, account):
    """Request a code, use it, and sign in with the new password."""
    sent = await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )
    code = sent.json()["debug_code"]

    reset = await client.post(
        "/auth/reset-password",
        json={
            "identifier": account["email"],
            "code": code,
            "new_password": "a-brand-new-password",
        },
    )
    assert reset.status_code == 200, reset.text

    signed_in = await client.post(
        "/auth/login",
        json={"identifier": account["email"], "password": "a-brand-new-password"},
    )
    assert signed_in.status_code == 200, signed_in.text

    # And the old one must no longer work.
    stale = await client.post(
        "/auth/login",
        json={"identifier": account["email"], "password": account["password"]},
    )
    assert stale.status_code == 401


@pytest.mark.asyncio
async def test_a_reset_code_cannot_be_used_twice(client, account):
    sent = await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )
    code = sent.json()["debug_code"]
    body = {"identifier": account["email"], "code": code, "new_password": "first-password-x"}

    assert (await client.post("/auth/reset-password", json=body)).status_code == 200

    replayed = await client.post(
        "/auth/reset-password",
        json={**body, "new_password": "second-password-x"},
    )
    assert replayed.status_code == 401, "a consumed code must not reset the password again"


@pytest.mark.asyncio
async def test_a_wrong_code_is_refused(client, account):
    await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )

    response = await client.post(
        "/auth/reset-password",
        json={
            "identifier": account["email"],
            "code": "000000",
            "new_password": "should-not-take-effect",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_otp_does_not_reveal_whether_an_account_exists(client):
    """The existence check is deliberately scoped to password reset. Sign-in
    must not become a way to enumerate who has an account."""
    response = await client.post(
        "/auth/otp/send",
        json={"identifier": f"{uuid.uuid4().hex}@testshop.pk", "purpose": "login"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_the_response_says_whether_the_code_was_actually_delivered(client, account):
    """Dev mode does not send anything, and the response must admit it rather
    than claim a code is on its way."""
    response = await client.post(
        "/auth/otp/send",
        json={"identifier": account["email"], "purpose": "reset_password"},
    )
    body = response.json()

    assert body["delivered"] is False
    assert "Could not send" in body["message"]
