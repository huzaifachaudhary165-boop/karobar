"""Getting your data out: full backup, restore, and the GSTR-1 return."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.schemas.common import Message
from app.services.backup_service import BackupService
from app.services.gst_service import GstService

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/backup", summary="Download everything as a JSON file")
async def download_backup(tenant: Tenant, db: DbSession) -> Response:
    # Exporting the whole shop is an owner/admin decision, not a report anyone
    # with read access can take away.
    tenant.require(Perm.BUSINESS_UPDATE)

    payload = await BackupService(db, tenant.actor).export()
    stamp = date.today().isoformat()
    safe_name = "".join(
        c for c in tenant.business.name if c.isalnum() or c in " -_"
    ).strip().replace(" ", "-") or "karobar"

    return Response(
        content=BackupService.to_bytes(payload),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-{stamp}.karobar.json"'
        },
    )


@router.post("/restore", summary="Load a backup file back in")
async def restore_backup(
    tenant: Tenant,
    db: DbSession,
    file: UploadFile = File(...),
    replace: bool = Query(
        False,
        description="Delete this business's existing records first. Off by default: "
                    "a restore should add, not destroy.",
    ),
) -> dict[str, object]:
    tenant.require(Perm.BUSINESS_UPDATE)

    payload = BackupService.from_bytes(await file.read())
    restored = await BackupService(db, tenant.actor).restore(payload, replace=replace)
    return {
        "restored": restored,
        "total": sum(restored.values()),
        "message": "Records already present were left alone."
        if not replace
        else "Existing records were replaced.",
    }


# response_model=None: this route returns either JSON or a CSV file download, and
# FastAPI cannot build one schema from `Response | dict`.
@router.get("/gstr1", response_model=None, summary="GSTR-1 for a period")
async def gstr1(
    tenant: Tenant,
    db: DbSession,
    start_date: date,
    end_date: date,
    format: str = Query("json", pattern="^(json|csv)$"),
) -> Response | dict:
    """The return in the offline utility's own JSON shape, or as a spreadsheet.

    This produces the file; you upload it to the GST portal yourself. Filing
    through the API requires a licensed GSP, which is not something that can be
    given away for free.
    """
    tenant.require(Perm.REPORT_EXPORT)

    report = await GstService(db, tenant.actor).gstr1(start_date, end_date)

    if format == "csv":
        return Response(
            content=GstService.to_csv(report),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="gstr1-{report["fp"]}.csv"'
            },
        )
    return report


@router.delete("/clear", response_model=Message,
               summary="Delete every transaction, keeping masters")
async def clear_transactions(tenant: Tenant, db: DbSession) -> Message:
    """Start a fresh year without retyping customers and items.

    Deliberately narrow: it removes bills, payments and expenses but leaves
    parties, items and settings in place — the thing people actually want when
    they say "clear the data".
    """
    tenant.require(Perm.BUSINESS_DELETE)

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.expense import Expense  # noqa: PLC0415
    from app.models.payment import Payment  # noqa: PLC0415
    from app.models.voucher import Voucher  # noqa: PLC0415

    removed = 0
    for model in (Payment, Expense, Voucher):
        rows = (
            await db.execute(
                select(model).where(model.business_id == tenant.business.id)
            )
        ).scalars().all()
        for row in rows:
            await db.delete(row)
            removed += 1

    return Message(message=f"{removed} transaction(s) deleted. Customers and items kept.")
