"""File upload and download."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DbSession, Tenant
from app.core.errors import NotFoundError
from app.models.system import Attachment
from app.schemas.common import Message
from app.services.storage_service import storage

router = APIRouter(prefix="/files", tags=["files"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Upload a file")
async def upload(
    tenant: Tenant,
    db: DbSession,
    file: UploadFile = File(...),
    owner_type: str | None = Form(None),
    owner_id: str | None = Form(None),
    folder: str = Form("uploads"),
) -> dict[str, object]:
    saved = await storage.save(
        await file.read(),
        filename=file.filename or "upload",
        business_id=tenant.business.id,
        content_type=file.content_type,
        folder=folder,
    )
    attachment = Attachment(
        business_id=tenant.business.id,
        owner_type=owner_type,
        owner_id=owner_id,
        file_name=str(saved["file_name"]),
        stored_name=str(saved["stored_name"]),
        url=str(saved["url"]),
        mime_type=str(saved["mime_type"]),
        size_bytes=int(saved["size_bytes"]),
        checksum=str(saved["checksum"]),
        uploaded_by=tenant.user.id,
    )
    db.add(attachment)
    await db.flush()
    return {
        "id": attachment.id,
        "file_name": attachment.file_name,
        "url": attachment.url,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
    }


@router.get("/{file_id}", summary="Download by attachment id")
async def download(file_id: str, tenant: Tenant, db: DbSession) -> Response:
    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == file_id, Attachment.business_id == tenant.business.id
            )
        )
    ).scalar_one_or_none()
    if attachment is None or not storage.exists(attachment.stored_name):
        raise NotFoundError("File not found.", details={"id": file_id})

    return FileResponse(
        storage.path_for(attachment.stored_name),
        media_type=attachment.mime_type or "application/octet-stream",
        filename=attachment.file_name,
    )


@router.delete("/{file_id}", response_model=Message, summary="Delete a file")
async def delete(file_id: str, tenant: Tenant, db: DbSession) -> Message:
    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == file_id, Attachment.business_id == tenant.business.id
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise NotFoundError("File not found.", details={"id": file_id})

    await storage.delete(attachment.stored_name)
    await db.delete(attachment)
    return Message(message="File deleted.")
