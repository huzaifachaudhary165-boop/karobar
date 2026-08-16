"""Every column a model declares must exist in the migrations.

This is the one class of bug the rest of the suite cannot see. Tests build
their schema from the models, so a column that exists in `models/` and nowhere
in `alembic/versions/` passes everything here and then fails on the live
database — as a 500 with no useful message, which reads like an outage rather
than a missing column.

It has now happened twice. The FBR settings went out with NOT NULL columns and
no server default; reminders went out missing `deleted_at` and `deleted_by`,
because `SoftDeleteMixin` was added to the model after the migration was
written and it brings three columns rather than the one that was obvious.

Both were found by a person poking at production. This finds them in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models import Base

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migrated_columns() -> dict[str, set[str]]:
    """Which columns the migrations give each table.

    Read per table, not as one blob. The first version of this checked whether
    a column name appeared anywhere in `alembic/versions/`, which is useless:
    `deleted_at` is on a dozen tables, so a table missing it still passed. That
    is worse than no test — it reads as coverage and provides none.

    Not a real parser. It reads `create_table`, `add_column` and `drop_column`,
    which is every way a column arrives or leaves in this project.
    """
    tables: dict[str, set[str]] = {}

    for path in sorted(VERSIONS.glob("*.py")):
        # Only what `upgrade()` does. A downgrade drops exactly what its
        # upgrade added, so reading both cancels every migration out and the
        # whole check quietly passes on an empty result.
        text = path.read_text(encoding="utf-8").split("def downgrade")[0]

        # op.create_table('x', sa.Column('a'…), sa.Column('b'…), …)
        for match in re.finditer(r"op\.create_table\(\s*['\"](\w+)['\"]", text):
            name = match.group(1)
            # Up to the next op.* call, which is where the argument list ends
            # in every migration this project writes.
            rest = text[match.end():]
            block = re.split(r"\n\s*op\.", rest, maxsplit=1)[0]
            tables.setdefault(name, set()).update(
                re.findall(r"sa\.Column\(\s*['\"](\w+)['\"]", block)
            )

        for name, column in re.findall(
            r"op\.add_column\(\s*['\"](\w+)['\"],\s*sa\.Column\(\s*['\"](\w+)['\"]",
            text,
        ):
            tables.setdefault(name, set()).add(column)

        for name, column in re.findall(
            r"op\.drop_column\(\s*['\"](\w+)['\"],\s*['\"](\w+)['\"]", text
        ):
            tables.get(name, set()).discard(column)

    return tables


@pytest.fixture(scope="module")
def migrations() -> dict[str, set[str]]:
    return _migrated_columns()


def test_there_are_migrations_to_check():
    # A guard on the guard: an empty glob would make every assertion below
    # vacuously true and this file would protect nothing.
    assert list(VERSIONS.glob("*.py")), "no migrations found to check against"


def test_every_table_appears_in_a_migration(migrations: dict[str, set[str]]):
    missing = sorted(set(Base.metadata.tables) - set(migrations))
    assert not missing, (
        f"tables with no migration — they exist only in the tests: {missing}"
    )


def test_every_column_appears_in_its_own_table_s_migration(
    migrations: dict[str, set[str]],
):
    """The check that matters, and the one the first attempt got wrong.

    Every query against a table selects every column the model declares, so one
    missing column is not a degraded feature — it is a 500 on everything that
    touches the table.
    """
    gaps: list[str] = []

    for table_name, table in Base.metadata.tables.items():
        migrated = migrations.get(table_name, set())
        if not migrated:
            continue  # reported by the test above
        for column in table.columns:
            if column.name not in migrated:
                gaps.append(f"{table_name}.{column.name}")

    assert not gaps, (
        "columns declared on a model and never migrated. These pass every test "
        f"here and 500 on the live database: {sorted(gaps)}"
    )


def test_soft_deleted_tables_carry_all_three_columns(migrations: str):
    """The specific shape that got through.

    `is_deleted` is the obvious one and the easy one to write by hand. The
    mixin brings two more, and a table with only the first fails every query
    against it.
    """
    for table_name, table in Base.metadata.tables.items():
        columns = {c.name for c in table.columns}
        if "is_deleted" not in columns:
            continue

        for partner in ("deleted_at", "deleted_by"):
            assert partner in columns, (
                f"{table_name} has is_deleted without {partner} — the model and "
                "the mixin disagree"
            )


def test_migration_revisions_form_one_chain():
    """Two heads means `alembic upgrade head` refuses to run at all, and the
    deploy fails with nothing applied."""
    downs: list[str] = []
    revs: list[str] = []

    for path in VERSIONS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if rev := re.search(r"^revision: str = ['\"]([^'\"]+)", text, re.M):
            revs.append(rev.group(1))
        if down := re.search(r"^down_revision: .*?= ['\"]([^'\"]+)", text, re.M):
            downs.append(down.group(1))

    heads = set(revs) - set(downs)
    assert len(heads) == 1, f"expected one head, found {sorted(heads)}"
    assert len(revs) == len(set(revs)), "two migrations share a revision id"
