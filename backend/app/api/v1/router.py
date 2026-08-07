"""v1 router — mounts every endpoint module."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    ai, auth, businesses, data, expenses, fbr, files, finance, health, integrations,
    items, loyalty, manufacturing, notifications, parties, payments, pricing,
    recurring, reports, sync, vouchers,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(businesses.router)
api_router.include_router(parties.router)
api_router.include_router(items.router)
api_router.include_router(vouchers.router)
api_router.include_router(payments.router)
api_router.include_router(expenses.router)
api_router.include_router(finance.router)
api_router.include_router(pricing.router)
api_router.include_router(recurring.router)
api_router.include_router(loyalty.router)
api_router.include_router(manufacturing.router)
api_router.include_router(fbr.router)
api_router.include_router(reports.router)
api_router.include_router(notifications.router)
api_router.include_router(ai.router)
api_router.include_router(sync.router)
api_router.include_router(files.router)
api_router.include_router(integrations.router)
api_router.include_router(data.router)
