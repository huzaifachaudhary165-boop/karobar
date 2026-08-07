"""Printable barcode labels.

A label sheet has one property that matters above all: what comes out of the
printer must line up with the sticker paper. Everything here is about that, and
about the sheet still being usable when an item has no barcode to print.
"""

from __future__ import annotations

import re

import pytest


async def _label_item(client, name: str, *, barcode: str | None, price: int = 250) -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name,
            "sale_price": price,
            "purchase_price": price - 50,
            "mrp": price + 30,
            **({"barcode": barcode} if barcode else {}),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _labels_in(html: str) -> int:
    return len(re.findall(r'<div class="label">', html))


# ── the sizes a shop can buy ───────────────────────────────────────
@pytest.mark.asyncio
async def test_the_label_sizes_are_offered_by_the_name_on_the_box(shop):
    sizes = (await shop["client"].get("/items/labels/sizes")).json()
    keys = {s["key"] for s in sizes}

    assert "a4_65" in keys, "the commonest A4 sticker sheet"
    assert any(s["is_roll"] for s in sizes), "a label printer takes roll stock"

    sheet = next(s for s in sizes if s["key"] == "a4_65")
    assert sheet["per_sheet"] == sheet["columns"] * sheet["rows"] == 65
    assert "38" in sheet["name"] and "21" in sheet["name"]


# ── the sheet itself ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_asking_for_ten_labels_prints_ten(shop):
    client = shop["client"]
    item = await _label_item(client, "Shan Masala 50g", barcode="5901234123457")

    sheet = await client.post(
        "/items/labels", json={"items": [{"item_id": item["id"], "qty": 10}]}
    )
    assert sheet.status_code == 200, sheet.text
    assert _labels_in(sheet.text) == 10


@pytest.mark.asyncio
async def test_several_items_print_together(shop):
    client = shop["client"]
    one = await _label_item(client, "Tapal Danedar 200g", barcode="5901234123457")
    two = await _label_item(client, "Lipton Yellow 190g", barcode="4006381333931")

    sheet = await client.post(
        "/items/labels",
        json={
            "items": [
                {"item_id": one["id"], "qty": 3},
                {"item_id": two["id"], "qty": 4},
            ]
        },
    )
    assert _labels_in(sheet.text) == 7
    assert "Tapal Danedar 200g" in sheet.text
    assert "Lipton Yellow 190g" in sheet.text


@pytest.mark.asyncio
async def test_the_sheet_is_laid_out_to_the_stock_it_will_be_printed_on(shop):
    client = shop["client"]
    item = await _label_item(client, "Nestle Milkpak 1L", barcode="5901234123457")

    sheet = await client.post(
        "/items/labels",
        json={"items": [{"item_id": item["id"], "qty": 2}], "size": "a4_24"},
    )
    html = sheet.text

    assert "repeat(3, 64.0mm)" in html, "three columns of 64mm labels"
    assert "height: 34.0mm" in html
    assert "size: A4" in html


@pytest.mark.asyncio
async def test_roll_stock_puts_one_label_on_each_page(shop):
    """A label printer feeds one sticker at a time; a grid would print the
    whole roll onto the first one."""
    client = shop["client"]
    item = await _label_item(client, "Olpers 1L", barcode="5901234123457")

    sheet = await client.post(
        "/items/labels",
        json={"items": [{"item_id": item["id"], "qty": 3}], "size": "roll_50x25"},
    )
    html = sheet.text

    assert "size: 50mm 25mm" in html
    assert "page-break-after: always" in html


@pytest.mark.asyncio
async def test_a_part_used_sheet_can_be_started_partway_down(shop):
    """A shop that peeled nine labels yesterday should not waste the rest of
    the sticker paper to print one more today."""
    client = shop["client"]
    item = await _label_item(client, "Dalda 1kg", barcode="5901234123457")

    sheet = await client.post(
        "/items/labels",
        json={"items": [{"item_id": item["id"], "qty": 1}], "start_at": 10},
    )
    # Nine blanks skipped, then the one that was asked for.
    assert _labels_in(sheet.text) == 10
    assert sheet.text.count("Dalda 1kg") == 1


# ── barcodes on the sticker ────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_bars_are_drawn_as_an_svg_scaled_by_viewbox(shop):
    client = shop["client"]
    item = await _label_item(client, "Sooper Biscuit", barcode="5901234123457")

    html = (
        await client.post("/items/labels", json={"items": [{"item_id": item["id"]}]})
    ).text

    assert "<svg" in html
    assert 'viewBox="0 0 95 100"' in html, "an EAN-13 symbol is 95 modules wide"
    assert "<rect" in html


@pytest.mark.asyncio
async def test_an_item_with_no_barcode_still_gets_a_label(shop):
    """The name and price are worth printing on their own, and a blank sticker
    would be taken for a printer fault."""
    client = shop["client"]
    item = await _label_item(client, "Loose Sugar 1kg", barcode=None)

    html = (
        await client.post("/items/labels", json={"items": [{"item_id": item["id"]}]})
    ).text

    assert _labels_in(html) == 1
    assert "Loose Sugar 1kg" in html
    assert "no barcode" in html


@pytest.mark.asyncio
async def test_what_goes_on_the_sticker_can_be_chosen(shop):
    client = shop["client"]
    item = await _label_item(client, "Knorr Soup", barcode="5901234123457", price=180)

    bare = (
        await client.post(
            "/items/labels",
            json={
                "items": [{"item_id": item["id"]}],
                "show_name": False,
                "show_price": False,
                "show_code": False,
            },
        )
    ).text
    assert "Knorr Soup" not in bare
    assert "<svg" in bare, "the bars are the point of the label"

    full = (
        await client.post(
            "/items/labels",
            json={
                "items": [{"item_id": item["id"]}],
                "show_mrp": True,
                "show_shop": True,
            },
        )
    ).text
    assert "Knorr Soup" in full
    assert "MRP" in full
    assert "Test Traders" in full, "the shop name when asked for"


# ── refusals ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_unknown_label_size_is_refused_with_the_options(shop):
    client = shop["client"]
    item = await _label_item(client, "Anything", barcode="5901234123457")

    refused = await client.post(
        "/items/labels",
        json={"items": [{"item_id": item["id"]}], "size": "a4_1000"},
    )
    assert refused.status_code == 422, refused.text
    assert "a4_65" in str(refused.json()["error"]["details"])


@pytest.mark.asyncio
async def test_an_unknown_item_is_refused(shop):
    refused = await shop["client"].post(
        "/items/labels",
        json={"items": [{"item_id": "00000000-0000-0000-0000-000000000000"}]},
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_a_job_too_large_for_one_run_is_refused(shop):
    client = shop["client"]
    item = await _label_item(client, "Bulk Item", barcode="5901234123457")

    refused = await client.post(
        "/items/labels", json={"items": [{"item_id": item["id"], "qty": 1000}] * 3}
    )
    assert refused.status_code == 422, refused.text
    assert "3000" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_the_same_item_listed_twice_prints_both_lots(shop):
    """A dict keyed on the item silently kept only the last of them."""
    client = shop["client"]
    item = await _label_item(client, "Repeated Item", barcode="5901234123457")

    sheet = await client.post(
        "/items/labels",
        json={
            "items": [
                {"item_id": item["id"], "qty": 3},
                {"item_id": item["id"], "qty": 4},
            ]
        },
    )
    assert _labels_in(sheet.text) == 7


@pytest.mark.asyncio
async def test_printing_nothing_is_refused(shop):
    refused = await shop["client"].post("/items/labels", json={"items": []})
    assert refused.status_code == 422, refused.text


# ── giving an item a code of its own ───────────────────────────────
@pytest.mark.asyncio
async def test_an_item_with_no_barcode_can_be_given_one(shop):
    client = shop["client"]
    item = await _label_item(client, "Loose Rice 1kg", barcode=None)

    assigned = await client.post("/items/labels/assign-barcode",
                                 params={"item_id": item["id"]})
    assert assigned.status_code == 200, assigned.text
    code = assigned.json()["barcode"]

    assert code.startswith("200"), "the range reserved for in-store codes"
    assert len(code) == 13
    assert (await client.get(f"/items/{item['id']}")).json()["barcode"] == code


@pytest.mark.asyncio
async def test_the_new_code_scans_as_a_real_ean13(shop):
    from app.core.barcodes import encode_ean13

    client = shop["client"]
    item = await _label_item(client, "Loose Daal 1kg", barcode=None)
    code = (
        await client.post("/items/labels/assign-barcode", params={"item_id": item["id"]})
    ).json()["barcode"]

    assert encode_ean13(code).module_count == 95


@pytest.mark.asyncio
async def test_two_items_never_get_the_same_code(shop):
    client = shop["client"]
    codes = set()
    for index in range(6):
        item = await _label_item(client, f"Loose Item {index}", barcode=None)
        codes.add(
            (
                await client.post(
                    "/items/labels/assign-barcode", params={"item_id": item["id"]}
                )
            ).json()["barcode"]
        )
    assert len(codes) == 6


@pytest.mark.asyncio
async def test_an_item_that_already_has_a_code_keeps_it(shop):
    client = shop["client"]
    item = await _label_item(client, "Shan Biryani", barcode="5901234123457")

    kept = await client.post("/items/labels/assign-barcode", params={"item_id": item["id"]})
    assert kept.json()["barcode"] == "5901234123457"
    assert kept.json()["symbology"] == "existing"


@pytest.mark.asyncio
async def test_the_minted_code_prints(shop):
    """The whole point: an item that could not be scanned now can be."""
    client = shop["client"]
    item = await _label_item(client, "Home-made Achaar", barcode=None)
    await client.post("/items/labels/assign-barcode", params={"item_id": item["id"]})

    html = (
        await client.post("/items/labels", json={"items": [{"item_id": item["id"]}]})
    ).text

    assert "no barcode" not in html
    assert 'viewBox="0 0 95 100"' in html
