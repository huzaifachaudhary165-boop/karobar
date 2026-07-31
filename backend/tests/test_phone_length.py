"""A phone number that is too long must say so, not 500.

Normalising a number can make it *longer* — `normalise_phone` prepends a "+".
Pydantic's `max_length` runs against the raw input, so twenty typed digits
passed validation, became twenty-one characters, and were then refused by the
database. The shopkeeper saw "a database error occurred" on a screen whose only
real problem was one digit too many, with nothing pointing at the field.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.party import PartyCreate
from app.utils.phone import MAX_PHONE_LENGTH, clean_phone


@pytest.mark.parametrize("digits", range(7, 20))
def test_ordinary_numbers_are_accepted_and_fit(digits):
    cleaned = clean_phone("1" * digits)
    assert cleaned is not None
    assert len(cleaned) <= MAX_PHONE_LENGTH, (
        f"{digits} digits normalised to {len(cleaned)} characters, which the "
        "database column cannot hold"
    )


def test_the_boundary_that_used_to_500(sample=None):
    """Twenty digits is the exact case that reached the database and failed."""
    with pytest.raises(ValueError) as exc:
        clean_phone("1" * 20)

    message = str(exc.value)
    assert "too many" in message
    assert "20" in message or "21" in message, message


@pytest.mark.parametrize("value", ["1" * 20, "1" * 25, "+" + "9" * 22])
def test_an_over_long_number_is_a_field_error_not_a_crash(value):
    with pytest.raises(ValidationError) as exc:
        PartyCreate(name="Too Long", phone=value)

    errors = exc.value.errors()
    assert any(e["loc"] == ("phone",) for e in errors), errors


def test_the_message_names_the_problem_rather_than_the_rule():
    """"String should have at most 20 characters" is about our column. A
    shopkeeper needs to know they typed an extra digit."""
    try:
        clean_phone("1" * 22)
    except ValueError as exc:
        assert "digits" in str(exc)
        assert "extra digit" in str(exc) or "country code" in str(exc)
    else:
        pytest.fail("expected a ValueError")


def test_formatting_is_ignored_when_measuring_length():
    """Spaces and dashes are stripped, so a normal number written out long-hand
    must not be rejected for looking long."""
    assert clean_phone("0300 123 4567") == clean_phone("03001234567")
    assert clean_phone("0300-123-4567") == clean_phone("03001234567")


def test_blank_stays_blank():
    assert clean_phone(None) is None
    assert clean_phone("") is None
    assert clean_phone("   ") is None


@pytest.mark.asyncio
async def test_the_api_reports_it_as_a_field_error(shop):
    """End to end: the response must point at `phone`, not read as a server
    fault the shopkeeper can do nothing about."""
    response = await shop["client"].post(
        "/parties",
        json={"name": "Long Number Co", "party_type": "customer", "phone": "1" * 20},
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "phone" in body["error"]["details"]["fields"]


@pytest.mark.asyncio
async def test_a_rejected_party_is_not_in_the_list_afterwards(shop):
    """Nothing may be left behind by a request that was refused."""
    client = shop["client"]
    await client.post(
        "/parties",
        json={"name": "Ghost Party", "party_type": "customer", "phone": "1" * 20},
    )

    listing = (await client.get("/parties?page=1&size=50&search=Ghost")).json()
    assert not any(p["name"] == "Ghost Party" for p in listing["items"]), (
        "the party was refused on screen but stored anyway"
    )


@pytest.mark.asyncio
async def test_a_long_number_on_the_business_is_also_a_field_error(shop):
    """The same validator is used for shop details and for sign-up."""
    response = await shop["client"].patch(
        "/businesses/current", json={"phone": "1" * 20}
    )
    assert response.status_code == 422, response.text
