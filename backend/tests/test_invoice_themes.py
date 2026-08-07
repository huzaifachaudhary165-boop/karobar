"""Invoice themes.

The one thing that must never happen here is a bill that will not print. Every
fallback below exists because a settings row written by an older build, or a
theme someone removed, must not stop a shopkeeper handing a customer their bill.
"""

from __future__ import annotations

import pytest

from app.services.invoice_templates import TEMPLATES as LEGACY
from app.services.invoice_themes import DEFAULT_THEME, LAYOUTS, THEMES, get_theme


# ── the registry ───────────────────────────────────────────────────
def test_there_are_enough_looks_to_choose_from():
    assert len(THEMES) >= 20


def test_every_theme_has_a_name_a_shop_would_understand():
    for key, theme in THEMES.items():
        assert theme.key == key
        assert theme.name and not theme.name.islower(), key
        assert theme.layout in LAYOUTS, key


def test_the_default_exists():
    assert DEFAULT_THEME in THEMES


def test_every_layout_family_is_actually_used():
    """A layout nobody uses is dead code pretending to be a feature."""
    used = {theme.layout for theme in THEMES.values()}
    assert used == set(LAYOUTS)


def test_there_is_something_for_every_paper_a_shop_might_load():
    papers = {theme.paper for theme in THEMES.values()}
    assert "A4" in papers
    assert "A5" in papers
    assert "Letter" in papers
    assert any("80mm" in p for p in papers)
    assert any("58mm" in p for p in papers)


def test_roll_themes_are_the_ones_marked_as_rolls():
    for theme in THEMES.values():
        assert theme.is_roll == ("mm" in theme.paper), theme.key


def test_a_compact_theme_really_is_smaller_than_a_roomy_one():
    compact = THEMES["compact"]
    roomy = THEMES["elegant"]
    assert compact.base_pt < roomy.base_pt


# ── resolving one ──────────────────────────────────────────────────
def test_an_unknown_theme_falls_back_rather_than_refusing_to_print():
    assert get_theme("something-removed").key == DEFAULT_THEME
    assert get_theme(None).key == DEFAULT_THEME
    assert get_theme("").key == DEFAULT_THEME


def test_a_theme_name_is_matched_regardless_of_case_or_spacing():
    assert get_theme("  Classic_Blue ").key == "classic_blue"


def test_a_shop_colour_overrides_a_coloured_theme():
    assert get_theme("classic", accent="#7C3AED").accent == "#7C3AED"


def test_a_shop_colour_does_not_tint_a_black_and_white_theme():
    """A monochrome layout tinted orange is neither of the two things someone
    chose."""
    assert get_theme("minimal", accent="#7C3AED").accent == "#1a1a1a"


def test_overriding_the_colour_leaves_everything_else_alone():
    original = THEMES["compact"]
    tinted = get_theme("compact", accent="#000080")
    assert tinted.density == original.density
    assert tinted.zebra == original.zebra
    assert tinted.paper == original.paper


# ── rendering ──────────────────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(THEMES))
async def test_every_theme_renders_a_complete_bill(shop, key):
    """Rendered through the real preview endpoint, so a template that breaks on
    one theme cannot ship looking fine on the other twenty-five."""
    response = await shop["client"].get(
        "/businesses/current/invoice-preview", params={"theme": key}
    )
    assert response.status_code == 200, f"{key}: {response.text[:200]}"

    html = response.text
    assert "<!doctype html>" in html.lower(), key
    assert "Ahmed Traders" in html, f"{key} lost the customer"
    assert "Sugar 50kg Bag" in html, f"{key} lost a line"
    assert "Test Traders" in html, f"{key} lost the shop name"
    assert html.count("<tr") >= 4, f"{key} lost rows"


@pytest.mark.asyncio
async def test_the_preview_shows_every_row_a_real_bill_can_grow(shop):
    """Discount, tax, delivery, round-off and a part payment all at once — a
    preview without them hides exactly the rows that misalign a layout."""
    html = (
        await shop["client"].get(
            "/businesses/current/invoice-preview", params={"theme": "classic_blue"}
        )
    ).text

    for row in ("Subtotal", "Discount", "Tax", "Delivery", "Round off", "Total",
                "Paid", "Balance"):
        assert row in html, f"the sample does not exercise '{row}'"


@pytest.mark.asyncio
async def test_the_four_original_names_keep_their_original_layouts(shop):
    """`classic`, `minimal`, `gst` and `receipt` are names shops already chose,
    and they render from the hand-written templates rather than the theme
    engine. An upgrade must not quietly change what a shop's bills look like —
    the new looks are new names, not replacements."""
    from app.services.invoice_templates import CLASSIC

    html = (
        await shop["client"].get(
            "/businesses/current/invoice-preview", params={"theme": "classic"}
        )
    ).text

    # A marker that only exists in the hand-written Classic layout.
    signature = CLASSIC.split("<style>")[1][:80]
    assert any(
        fragment.strip() and fragment.strip() in html
        for fragment in signature.splitlines()
    ), "classic no longer renders from its original template"


@pytest.mark.asyncio
async def test_a_roll_theme_leaves_out_what_will_not_fit(shop):
    html = (
        await shop["client"].get(
            "/businesses/current/invoice-preview", params={"theme": "receipt_58"}
        )
    ).text

    assert "58mm" in html
    assert "Authorised signature" not in html, "no room for it on a till roll"


@pytest.mark.asyncio
async def test_a_letterhead_theme_leaves_the_top_of_the_page_alone(shop):
    html = (
        await shop["client"].get(
            "/businesses/current/invoice-preview", params={"theme": "letterhead"}
        )
    ).text
    assert "margin-top: 38mm" in html


@pytest.mark.asyncio
async def test_an_unknown_theme_previews_the_default_rather_than_failing(shop):
    response = await shop["client"].get(
        "/businesses/current/invoice-preview", params={"theme": "nonsense"}
    )
    assert response.status_code == 200
    assert "Ahmed Traders" in response.text


# ── the picker and the setting ─────────────────────────────────────
@pytest.mark.asyncio
async def test_the_themes_are_listed_for_the_picker(shop):
    listed = (await shop["client"].get("/businesses/invoice-themes")).json()
    assert len(listed) == len(THEMES)
    assert {t["key"] for t in listed} == set(THEMES)
    assert all(t["name"] for t in listed)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["modern_indigo", "compact", "receipt_58", "elegant"])
async def test_a_theme_can_actually_be_saved(shop, key):
    """A hard-coded alternation in the schema meant adding a theme silently
    made it unsavable, which looks from the outside like a broken picker."""
    saved = await shop["client"].patch(
        "/businesses/current/settings", json={"invoice_template": key}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["invoice_template"] == key


@pytest.mark.asyncio
async def test_the_original_four_layouts_still_save_and_print(shop):
    """Shops are already on these. An upgrade must not change what they print."""
    for key in LEGACY:
        saved = await shop["client"].patch(
            "/businesses/current/settings", json={"invoice_template": key}
        )
        assert saved.status_code == 200, f"{key}: {saved.text}"

        preview = await shop["client"].get(
            "/businesses/current/invoice-preview", params={"theme": key}
        )
        assert preview.status_code == 200, key
        assert "Ahmed Traders" in preview.text, key


@pytest.mark.asyncio
async def test_a_theme_that_does_not_exist_is_refused_on_save(shop):
    refused = await shop["client"].patch(
        "/businesses/current/settings", json={"invoice_template": "gold-plated"}
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_the_chosen_theme_is_what_a_real_invoice_prints_in(shop):
    client = shop["client"]
    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [
                    {"item_id": shop["sugar"]["id"], "qty": 1, "rate": 7400, "tax_rate": 0}
                ],
            },
        )
    ).json()

    await client.patch(
        "/businesses/current/settings", json={"invoice_template": "modern_rose"}
    )
    html = (await client.get(f"/vouchers/{invoice['id']}/html")).text

    assert "#E11D48" in html or "border-left" in html, "the sidebar layout is in use"
    assert shop["customer"]["name"] in html
