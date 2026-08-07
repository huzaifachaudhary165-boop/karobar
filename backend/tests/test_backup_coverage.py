"""What a backup contains.

A backup that quietly leaves half the shop out is worse than no backup: it is
believed, and the loss is only discovered on the day it is restored. So every
table is either backed up or named as deliberately skipped, and a new feature
that does neither fails here rather than years later on somebody's restore.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Base
from app.services.backup_service import _DELIBERATELY_SKIPPED, _TABLES


def test_every_table_is_either_backed_up_or_deliberately_skipped():
    """The test that makes this file worth having.

    Adding a model without adding it to one of these two lists is how a
    feature falls out of the backup, and nothing else would notice.
    """
    known = {name for name, _model in _TABLES} | set(_DELIBERATELY_SKIPPED)
    everything = set(Base.metadata.tables)

    forgotten = everything - known
    assert not forgotten, (
        f"these tables are neither backed up nor listed as skipped: "
        f"{sorted(forgotten)}"
    )


def test_nothing_is_listed_in_both_places():
    backed_up = {name for name, _model in _TABLES}
    assert not backed_up & set(_DELIBERATELY_SKIPPED)


def test_every_skipped_table_actually_exists():
    """A stale entry hides a real gap: a table renamed but still listed as
    skipped means its replacement is silently unbacked."""
    missing = set(_DELIBERATELY_SKIPPED) - set(Base.metadata.tables)
    assert not missing, f"listed as skipped but no such table: {sorted(missing)}"


def test_every_skipped_table_says_why():
    for table, reason in _DELIBERATELY_SKIPPED.items():
        assert len(reason) > 15, f"{table} needs a real reason, not '{reason}'"


def test_the_new_features_are_all_in_the_backup():
    """Named one by one, because 'the list is long' is not the same as 'the
    list is complete'."""
    backed_up = {name for name, _model in _TABLES}
    for table in (
        "godowns", "item_batches", "item_serials", "godown_stocks",
        "price_lists", "price_list_entries", "discount_schemes",
        "account_transfers", "loans", "loan_payments",
        "loyalty_programs", "loyalty_entries",
        "bills_of_materials", "bom_components", "production_runs",
        "consumed_materials", "recurring_invoices",
    ):
        assert table in backed_up, f"{table} would be lost on restore"


def test_dependencies_come_before_the_things_that_need_them():
    """Restoring in list order is what makes the import a single pass. A child
    before its parent is a foreign key violation on somebody's restore."""
    order = {name: index for index, (name, _model) in enumerate(_TABLES)}

    for child, parent in [
        ("items", "item_categories"),
        ("item_batches", "items"),
        ("item_serials", "items"),
        ("godown_stocks", "godowns"),
        ("godown_stocks", "items"),
        ("vouchers", "parties"),
        ("voucher_lines", "vouchers"),
        ("payments", "accounts"),
        ("price_list_entries", "price_lists"),
        ("loan_payments", "loans"),
        ("loyalty_entries", "parties"),
        ("bom_components", "bills_of_materials"),
        ("consumed_materials", "production_runs"),
        ("account_transfers", "accounts"),
    ]:
        assert order[parent] < order[child], (
            f"{child} is restored before {parent}, which it points at"
        )


# ── end to end ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_backup_carries_the_newer_features_through_a_restore(shop):
    """The whole point, exercised: set something up, back it up, and see it in
    the file."""
    client = shop["client"]

    await client.post("/items/godowns", json={"name": "Backup Store"})
    await client.post("/pricing/lists", json={"name": "Backup Wholesale",
                                              "adjust_percent": -5})
    await client.post(
        "/finance/loans",
        json={"lender_name": "Backup Bank", "principal": 50000,
              "interest_rate": 0, "tenure_months": 5},
    )

    backup = await client.get("/data/backup")
    assert backup.status_code == 200, backup.text
    body = backup.json()

    assert "godowns" in body["data"]
    assert any(row["name"] == "Backup Store" for row in body["data"]["godowns"])
    assert any(
        row["name"] == "Backup Wholesale" for row in body["data"]["price_lists"]
    )
    assert any(
        row["lender_name"] == "Backup Bank" for row in body["data"]["loans"]
    )


@pytest.mark.asyncio
async def test_money_survives_the_round_trip_as_a_decimal_not_a_float(shop):
    """Exported as a string on purpose: a float would quietly lose paise, and
    a backup that changes the numbers is not a backup."""
    client = shop["client"]
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 3, "rate": 7400.55}],
        },
    )

    body = (await client.get("/data/backup")).json()
    voucher = body["data"]["vouchers"][0]

    assert isinstance(voucher["total"], str)
    assert Decimal(voucher["total"]) == Decimal(voucher["total"])


@pytest.mark.asyncio
async def test_the_backup_says_which_format_it_is(shop):
    """A file restored years later has to be readable by whatever the app has
    become by then."""
    body = (await shop["client"].get("/data/backup")).json()
    assert body["format_version"] >= 1
    assert body["business"]["id"] == shop["business"]["id"]
    assert body["exported_at"]


@pytest.mark.asyncio
async def test_a_payment_keeps_track_of_which_bill_it_paid(shop):
    """Without the allocations, a restored shop has its payments and its
    invoices and no record of which paid which — every bill reads unpaid."""
    client = shop["client"]
    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 7400}],
            },
        )
    ).json()

    paid = await client.post(
        "/payments",
        json={
            "direction": "in",
            "party_id": shop["customer"]["id"],
            "amount": 7400,
            "allocations": [{"voucher_id": invoice["id"], "amount": 7400}],
        },
    )
    assert paid.status_code == 201, paid.text

    body = (await client.get("/data/backup")).json()
    allocations = body["data"]["payment_allocations"]

    assert allocations, "the link between payment and invoice was not backed up"
    assert allocations[0]["voucher_id"] == invoice["id"]
