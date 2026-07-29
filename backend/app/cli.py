"""Developer CLI.

    python -m app.cli seed      # demo business with realistic data
    python -m app.cli reset     # drop and recreate every table
    python -m app.cli check     # configuration sanity report
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import date, timedelta
from decimal import Decimal

from app.core.config import settings
from app.core.database import SessionLocal, close_db, engine, init_db
from app.core.logging import configure_logging, log
from app.core.money import money
from app.core.security import hash_password
from app.models import Base
from app.models.enums import PartyType, PaymentDirection, VoucherType
from app.models.user import User
from app.schemas.item import ItemCreate
from app.schemas.party import PartyCreate
from app.schemas.payment import ExpenseCreate
from app.schemas.voucher import PaymentInline, VoucherCreate, VoucherLineInput
from app.services.base import ActorContext
from app.services.business_service import BusinessService
from app.services.expense_service import ExpenseService
from app.services.item_service import ItemService
from app.services.party_service import PartyService
from app.services.payment_service import PaymentService
from app.services.voucher_service import VoucherService

DEMO_EMAIL = "demo@karobar.app"
DEMO_PASSWORD = "demo1234"

ITEMS = [
    # (name, unit, purchase, sale, opening stock, low-stock, tax %)
    ("Sugar (50 Kg Bag)", "Bag", 6800, 7400, 40, 8, 0),
    ("Wheat Flour (20 Kg)", "Bag", 2100, 2350, 60, 12, 0),
    ("Cooking Oil (5 L)", "Btl", 2450, 2750, 35, 10, 17),
    ("Basmati Rice (5 Kg)", "Pkt", 1550, 1790, 50, 10, 0),
    ("Tea Leaves (900 g)", "Pkt", 1180, 1350, 28, 6, 17),
    ("Milk Powder (400 g)", "Pkt", 780, 890, 22, 6, 17),
    ("Cement (50 Kg)", "Bag", 1180, 1290, 120, 25, 17),
    ("Detergent (1 Kg)", "Pkt", 340, 410, 45, 12, 17),
    ("Soap Bar", "Pcs", 95, 125, 200, 40, 17),
    ("Mineral Water (1.5 L)", "Btl", 55, 75, 180, 48, 0),
    ("Biscuits (Family Pack)", "Pkt", 145, 180, 90, 24, 17),
    ("Salt (800 g)", "Pkt", 42, 60, 150, 30, 0),
]

PARTIES = [
    ("Ahmed Traders", PartyType.CUSTOMER, "+923001234567", 0),
    ("Bilal General Store", PartyType.CUSTOMER, "+923214567890", 18500),
    ("Chaudhry Karyana", PartyType.CUSTOMER, "+923339876543", 0),
    ("Dawood & Sons", PartyType.CUSTOMER, "+923451112223", 42000),
    ("Eastern Mart", PartyType.CUSTOMER, "+923005556667", 0),
    ("Faisal Distributors", PartyType.SUPPLIER, "+923018889990", -125000),
    ("Global Foods Ltd", PartyType.SUPPLIER, "+923112223334", 0),
    ("Hamza Wholesale", PartyType.SUPPLIER, "+923224445556", -63000),
]

EXPENSES = [
    ("Shop rent", "Rent", 45000), ("Staff salaries", "Salaries", 78000),
    ("Electricity bill", "Utilities", 18500), ("Delivery van fuel", "Transport", 12400),
    ("Packaging material", "Packaging", 6800), ("Tea and refreshments", "Tea & Refreshments", 3200),
    ("Shop signboard repair", "Repairs & Maintenance", 9500),
]


async def seed() -> None:
    configure_logging()
    await init_db()
    rng = random.Random(20260728)  # deterministic demo data

    async with SessionLocal() as db:
        from sqlalchemy import select

        existing = (
            await db.execute(select(User).where(User.email == DEMO_EMAIL))
        ).scalar_one_or_none()
        if existing:
            print(f"Demo user already exists ({DEMO_EMAIL}). Run `reset` first to rebuild.")
            return

        user = User(
            name="Demo Shopkeeper",
            email=DEMO_EMAIL,
            phone="+923001112222",
            password_hash=hash_password(DEMO_PASSWORD),
            email_verified=True,
            language="en",
        )
        db.add(user)
        await db.flush()

        business = await BusinessService(db).create_for_owner(
            user,
            {
                "name": "Karobar Demo Store",
                "business_type": "retail",
                "country": "Pakistan",
                "city": "Lahore",
                "state": "Punjab",
                "phone": "+924235880000",
                "email": "shop@karobar.app",
                "address_line1": "Shop 14, Main Boulevard, Gulberg III",
                "tax_type": "sales_tax",
                "ntn": "1234567-8",
            },
        )
        user.active_business_id = business.id
        # Retail shops routinely sell ahead of a delivery being booked in, and the
        # demo timeline generates sales before every purchase is entered.
        cfg = await BusinessService(db).settings(business.id)
        cfg.allow_negative_stock = True
        await db.flush()

        actor = ActorContext(
            user_id=user.id, user_name=user.name, business_id=business.id,
            role="owner", source="seed",
        )
        parties_svc = PartyService(db, actor)
        items_svc = ItemService(db, actor)
        vouchers_svc = VoucherService(db, actor)
        payments_svc = PaymentService(db, actor)
        expenses_svc = ExpenseService(db, actor)

        parties = []
        for name, ptype, phone, opening in PARTIES:
            parties.append(
                await parties_svc.create(
                    PartyCreate(
                        name=name, party_type=ptype, phone=phone,
                        opening_balance=money(opening),
                        opening_balance_date=date.today() - timedelta(days=90),
                        credit_days=15 if ptype == PartyType.CUSTOMER else 30,
                    )
                )
            )

        items = []
        for name, unit, purchase, sale, stock, low, tax in ITEMS:
            items.append(
                await items_svc.create(
                    ItemCreate(
                        name=name, unit_label=unit,
                        purchase_price=money(purchase), sale_price=money(sale),
                        opening_stock=Decimal(stock),
                        opening_stock_value=money(purchase * stock),
                        low_stock_qty=Decimal(low), tax_rate=money(tax),
                        opening_stock_date=date.today() - timedelta(days=90),
                    )
                )
            )
        await db.commit()

        customers = [p for p in parties if p.party_type == PartyType.CUSTOMER]
        suppliers = [p for p in parties if p.party_type == PartyType.SUPPLIER]

        # Restock every 5 days across the whole catalogue, so sales have stock behind them.
        for day_offset in range(60, 0, -5):
            supplier = rng.choice(suppliers)
            picks = rng.sample(items, rng.randint(5, 8))
            await vouchers_svc.create(
                VoucherCreate(
                    voucher_type=VoucherType.PURCHASE,
                    party_id=supplier.id,
                    voucher_date=date.today() - timedelta(days=day_offset),
                    lines=[
                        VoucherLineInput(
                            item_id=item.id, qty=Decimal(rng.randint(25, 70)),
                            rate=item.purchase_price,
                        )
                        for item in picks
                    ],
                )
            )
        await db.commit()

        # 60 days of sales, busier on weekends.
        sale_ids: list[str] = []
        for day_offset in range(60, -1, -1):
            when = date.today() - timedelta(days=day_offset)
            for _ in range(rng.randint(2, 6) + (2 if when.weekday() >= 5 else 0)):
                customer = rng.choice(customers)
                picks = rng.sample(items, rng.randint(1, 4))
                lines = [
                    VoucherLineInput(
                        item_id=item.id,
                        qty=Decimal(rng.randint(1, 6)),
                        rate=item.sale_price,
                        discount_value=money(rng.choice([0, 0, 0, 2, 5])),
                    )
                    for item in picks
                ]
                pays_now = rng.random() < 0.65
                voucher = await vouchers_svc.create(
                    VoucherCreate(
                        voucher_type=VoucherType.SALE,
                        party_id=customer.id,
                        voucher_date=when,
                        lines=lines,
                    )
                )
                if pays_now:
                    await payments_svc.create_raw(
                        direction=PaymentDirection.IN,
                        amount=voucher.total,
                        party=customer,
                        mode=rng.choice(["cash", "cash", "bank", "easypaisa"]),
                        payment_date=when,
                        allocations=[{"voucher_id": voucher.id, "amount": voucher.total}],
                        source="seed",
                    )
                sale_ids.append(voucher.id)
            if day_offset % 10 == 0:
                await db.commit()
        await db.commit()

        for title, category, amount in EXPENSES:
            await expenses_svc.create(
                ExpenseCreate(
                    title=title, category_name=category, amount=money(amount),
                    expense_date=date.today() - timedelta(days=rng.randint(1, 28)),
                    payment_mode=rng.choice(["cash", "bank"]),
                )
            )

        # A quotation and a partly-paid invoice, so every status is represented.
        await vouchers_svc.create(
            VoucherCreate(
                voucher_type=VoucherType.QUOTATION,
                party_id=customers[0].id,
                lines=[
                    VoucherLineInput(item_id=items[0].id, qty=Decimal(10), rate=items[0].sale_price),
                    VoucherLineInput(item_id=items[3].id, qty=Decimal(5), rate=items[3].sale_price),
                ],
            )
        )
        partial = await vouchers_svc.create(
            VoucherCreate(
                voucher_type=VoucherType.SALE,
                party_id=customers[1].id,
                voucher_date=date.today() - timedelta(days=20),
                lines=[
                    VoucherLineInput(item_id=items[6].id, qty=Decimal(25), rate=items[6].sale_price)
                ],
                payment=PaymentInline(amount=money(10000), mode="cash"),
            )
        )
        await db.commit()

        totals = await vouchers_svc.stats(
            date.today() - timedelta(days=60), date.today(), VoucherType.SALE
        )

    await close_db()

    print(
        f"""
Demo data ready.

  Email     {DEMO_EMAIL}
  Password  {DEMO_PASSWORD}
  Business  Karobar Demo Store

  {totals['count']} sale invoices · {totals['total']} total · {totals['outstanding']} outstanding
  {len(items)} items · {len(parties)} parties · {len(EXPENSES)} expenses
  Partly-paid invoice: {partial.number}

Start the API with:  uvicorn app.main:app --reload
"""
    )


async def reset() -> None:
    configure_logging()
    confirm = input(f"Drop every table in {settings.DATABASE_URL}? Type 'yes': ")
    if confirm.strip().lower() != "yes":
        print("Cancelled.")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await close_db()
    print("Database reset.")


async def check() -> None:
    configure_logging()
    from app.ai.client import ai_client
    from app.core.database import ping_db

    print(f"\n{settings.APP_NAME} {settings.APP_VERSION} — {settings.ENVIRONMENT}\n")
    print(f"  Database    {settings.DATABASE_URL.split('@')[-1]}")
    print(f"  Reachable   {'yes' if await ping_db() else 'NO'}")
    print(f"  Tables      {len(Base.metadata.tables)}")
    print(f"  AI          {'configured (' + settings.AI_MODEL + ')' if ai_client.available else 'not configured'}")
    print(f"  WhatsApp    {'configured' if settings.WHATSAPP_ENABLED else 'not configured'}")
    print(f"  Email       {'SMTP configured' if settings.SMTP_USER else 'not configured'}")
    # Report where files actually go, not where they would go — the two differ
    # whenever STORAGE_BACKEND is set but its credentials are not.
    from app.services.storage_service import storage  # noqa: PLC0415

    if storage.backend == "supabase":
        print(f"  Storage     Supabase bucket '{settings.SUPABASE_BUCKET}'")
    else:
        print(f"  Storage     local disk — {settings.storage_path}")

    warnings = settings.sanity_check()
    if warnings:
        print("\n  Warnings:")
        for warning in warnings:
            print(f"    ! {warning}")
    else:
        print("\n  No configuration warnings.")
    print()
    await close_db()


COMMANDS = {"seed": seed, "reset": reset, "check": check}


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"Unknown command '{command}'. Available: {', '.join(COMMANDS)}")
        raise SystemExit(1)
    try:
        asyncio.run(handler())
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as exc:
        log.exception("cli.failed", command=command, error=str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
