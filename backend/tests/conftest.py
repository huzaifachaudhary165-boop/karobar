"""Test harness: a throwaway SQLite file per session, plus a signed-in client."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio

os.environ.update(
    ENVIRONMENT="test",
    DEBUG="false",
    DATABASE_URL="sqlite+aiosqlite:///./test_karobar.db",
    SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256-signing-1234567890",
    OTP_DEV_MODE="true",
    AI_ENABLED="false",
    RATE_LIMIT_ENABLED="false",
    STORAGE_DIR="./test_storage",
    # Never the real bucket: without this the suite inherits STORAGE_BACKEND
    # from .env and writes test uploads into production storage.
    STORAGE_BACKEND="local",
)

TEST_DB = Path(__file__).resolve().parents[1] / "test_karobar.db"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _database():
    if TEST_DB.exists():
        TEST_DB.unlink()

    from app.core.database import close_db, engine
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await close_db()
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except PermissionError:  # Windows keeps the handle briefly
            pass


@pytest_asyncio.fixture
async def client() -> AsyncGenerator:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=30
    ) as http_client:
        yield http_client


@pytest_asyncio.fixture
async def account(client) -> dict:
    """A registered owner with a business, plus an authorised client."""
    import uuid

    email = f"user_{uuid.uuid4().hex[:10]}@testshop.pk"
    response = await client.post(
        "/auth/register",
        json={
            "name": "Test Owner",
            "email": email,
            "password": "testpass123",
            "business_name": "Test Traders",
            "business_type": "retail",
            "country": "Pakistan",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()

    client.headers.update(
        {
            "Authorization": f"Bearer {data['tokens']['access_token']}",
            "X-Business-Id": data["active_business"]["id"],
            "X-Device-Id": "test-device-001",
        }
    )
    return {
        "email": email,
        "password": "testpass123",
        "user": data["user"],
        "business": data["active_business"],
        "tokens": data["tokens"],
        "client": client,
    }


@pytest_asyncio.fixture
async def shop(account) -> dict:
    """An account pre-loaded with one customer, one supplier and two items."""
    client = account["client"]

    customer = (
        await client.post(
            "/parties",
            json={"name": "Ahmed Traders", "party_type": "customer", "phone": "+923001234567"},
        )
    ).json()
    supplier = (
        await client.post(
            "/parties", json={"name": "Bilal Suppliers", "party_type": "supplier"}
        )
    ).json()
    sugar = (
        await client.post(
            "/items",
            json={
                "name": "Sugar 50kg", "sale_price": 7400, "purchase_price": 6800,
                "opening_stock": 100, "opening_stock_value": 680000,
                "unit_label": "Bag", "low_stock_qty": 10, "tax_rate": 0,
            },
        )
    ).json()
    oil = (
        await client.post(
            "/items",
            json={
                "name": "Cooking Oil 5L", "sale_price": 2750, "purchase_price": 2450,
                "opening_stock": 50, "opening_stock_value": 122500,
                "unit_label": "Btl", "tax_rate": 17,
            },
        )
    ).json()

    return {**account, "customer": customer, "supplier": supplier, "sugar": sugar, "oil": oil}

