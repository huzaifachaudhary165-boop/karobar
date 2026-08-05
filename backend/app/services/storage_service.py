"""File storage behind one interface: local disk in development, Supabase
Storage in production.

Both backends key files the same way — `<business_id>/<folder>/<uuid>_<name>` —
so the `stored_name` in the database stays valid if you switch, and the tenant
prefix means a bucket listing is already partitioned by shop.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from pathlib import Path
from typing import BinaryIO

import httpx

from app.core.config import settings
from app.core.errors import BusinessRuleError, IntegrationError, NotFoundError
from app.core.logging import log

ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic",
    "application/pdf",
    "text/csv", "text/plain",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

#: What a client sends when it does not know, or did not bother to say. Treating
#: it as a real answer is what made every upload from the app fail: Dio's
#: `MultipartFile.fromBytes` defaults to this, so a perfectly ordinary
#: `bill.jpg` arrived declared as a binary blob and was refused.
_UNKNOWN_MIME = {"application/octet-stream", "binary/octet-stream", ""}

#: Every extension this app accepts, spelled out.
#:
#: `mimetypes` is not usable as the source of truth here: it reads the *host's*
#: MIME registry, so the answer depends on the machine. Measured — `.webp`
#: returns None on one developer box, `.csv` comes back as `application/
#: vnd.ms-excel`, and `.xlsx` was unknown on the deployed runtime, which is why
#: a spreadsheet was refused by a message that said spreadsheets were fine.
#:
#: An upload being accepted or rejected must not depend on which computer the
#: server happens to be running on. Keep this in step with `ALLOWED_MIME`.
_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heic",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _resolve_mime(content_type: str | None, filename: str) -> str:
    """What this file actually is.

    The declared type wins only when it says something. A client that does not
    know announces `application/octet-stream`, and the filename is then a far
    better witness than a header that means "no idea".
    """
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared and declared not in _UNKNOWN_MIME:
        return declared

    suffix = Path(filename).suffix.lower()
    if suffix in _TYPE_BY_SUFFIX:
        return _TYPE_BY_SUFFIX[suffix]
    # Only for things outside the allow-list, where the answer does not decide
    # acceptance — it just makes the refusal message more specific.
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _describe(filename: str, mime: str) -> str:
    """A human name for a file type, for an error someone has to read."""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix:
        return f"A .{suffix} file"
    if mime and mime not in _UNKNOWN_MIME:
        return f"A {mime} file"
    return "That file"


class StorageService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base = base_dir or settings.storage_path

    @property
    def backend(self) -> str:
        """Supabase only when it is both selected and actually configured —
        a half-filled .env falls back to disk instead of failing every upload."""
        if settings.STORAGE_BACKEND == "supabase" and settings.supabase_storage_ready:
            return "supabase"
        return "local"

    # ── write ────────────────────────────────────────────────────
    async def save(
        self,
        data: bytes | BinaryIO,
        *,
        filename: str,
        business_id: str,
        content_type: str | None = None,
        folder: str = "uploads",
    ) -> dict[str, object]:
        raw = data if isinstance(data, bytes) else data.read()

        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        if len(raw) > max_bytes:
            raise BusinessRuleError(
                f"File is larger than {settings.MAX_UPLOAD_MB} MB.",
                details={"size_bytes": len(raw)},
            )
        if not raw:
            raise BusinessRuleError("The uploaded file is empty.")

        mime = _resolve_mime(content_type, filename)
        if mime not in ALLOWED_MIME:
            raise BusinessRuleError(
                # Name the file rather than the MIME type. "application/msword
                # is not supported" means nothing to a shopkeeper holding a
                # phone; "Word documents" does.
                f"{_describe(filename, mime)} cannot be attached. "
                "Photos, PDFs and spreadsheets can.",
                details={"mime_type": mime, "file_name": filename,
                         "allowed": sorted(ALLOWED_MIME)},
            )

        safe = _SAFE_NAME.sub("_", Path(filename).name)[:80] or "file"
        stored_name = f"{business_id}/{folder}/{uuid.uuid4().hex}_{safe}"

        if self.backend == "supabase":
            await self._supabase_put(stored_name, raw, mime)
        else:
            target = self._resolve(stored_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

        return {
            "stored_name": stored_name,
            "file_name": safe,
            # Always our own URL, never the storage provider's. The bucket stays
            # private, and every download goes through an authorised endpoint
            # that checks the file belongs to the caller's business.
            "url": f"/api/v1/files/{stored_name}",
            "mime_type": mime,
            "size_bytes": len(raw),
            "checksum": hashlib.sha256(raw).hexdigest(),
        }

    # ── read ─────────────────────────────────────────────────────
    async def read(self, stored_name: str) -> bytes:
        if self.backend == "supabase":
            return await self._supabase_get(stored_name)

        path = self._resolve(stored_name)
        if not path.exists():
            raise NotFoundError("File not found.", details={"name": stored_name})
        return path.read_bytes()

    async def delete(self, stored_name: str) -> bool:
        if self.backend == "supabase":
            return await self._supabase_delete(stored_name)

        try:
            path = self._resolve(stored_name)
        except BusinessRuleError:
            return False
        if path.exists():
            path.unlink()
            return True
        return False

    def exists(self, stored_name: str) -> bool:
        """Local-only, and only used to short-circuit a disk read. The Supabase
        path answers existence through `read` instead of a second round trip."""
        if self.backend == "supabase":
            return True
        try:
            return self._resolve(stored_name).exists()
        except BusinessRuleError:
            return False

    def path_for(self, stored_name: str) -> Path:
        return self._resolve(stored_name)

    def _resolve(self, stored_name: str) -> Path:
        """Confine every path to the storage root — the name is untrusted input."""
        candidate = (self.base / stored_name).resolve()
        root = self.base.resolve()
        if not candidate.is_relative_to(root):
            log.warning("storage.path_traversal_blocked", name=stored_name[:200])
            raise BusinessRuleError("Invalid file path.", code="invalid_path")
        return candidate

    # ── Supabase Storage ─────────────────────────────────────────
    @property
    def _supabase_root(self) -> str:
        return f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object"

    @property
    def _supabase_headers(self) -> dict[str, str]:
        # The service-role key bypasses row-level security, so it must never
        # leave the server — which is why downloads are proxied, not redirected.
        return {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_KEY,
        }

    def _object_url(self, stored_name: str) -> str:
        # `stored_name` is server-generated (uuid + sanitised basename), so it
        # cannot contain traversal segments — but keep it strict anyway.
        if ".." in stored_name or stored_name.startswith("/"):
            raise BusinessRuleError("Invalid file path.", code="invalid_path")
        return f"{self._supabase_root}/{settings.SUPABASE_BUCKET}/{stored_name}"

    async def _supabase_put(self, stored_name: str, raw: bytes, mime: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._object_url(stored_name),
                    headers={
                        **self._supabase_headers,
                        "Content-Type": mime,
                        "x-upsert": "true",
                    },
                    content=raw,
                )
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach file storage: {exc}") from exc

        if response.status_code >= 400:
            log.error(
                "storage.supabase_upload_failed",
                status=response.status_code,
                detail=response.text[:300],
            )
            raise IntegrationError(
                "The file could not be saved to storage.", code="storage_upload_failed"
            )

    async def _supabase_get(self, stored_name: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    self._object_url(stored_name), headers=self._supabase_headers
                )
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach file storage: {exc}") from exc

        if response.status_code >= 400:
            if _is_missing(response):
                raise NotFoundError("File not found.", details={"name": stored_name})
            log.error(
                "storage.supabase_read_failed",
                status=response.status_code,
                detail=response.text[:200],
            )
            raise IntegrationError(
                "The file could not be read from storage.", code="storage_read_failed"
            )
        return response.content

    async def _supabase_delete(self, stored_name: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.delete(
                    self._object_url(stored_name), headers=self._supabase_headers
                )
        except (httpx.HTTPError, BusinessRuleError):
            return False
        return response.status_code < 400


def _is_missing(response: httpx.Response) -> bool:
    """Supabase Storage answers a missing object with HTTP **400**, and puts the
    real 404 in the body:

        {"statusCode":"404","error":"not_found","message":"Object not found"}

    So the status line alone cannot be trusted here — without reading the body, a
    scan whose photo was deleted would surface as "storage is broken" instead of
    "that file is gone".
    """
    if response.status_code == 404:
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    return str(body.get("statusCode")) == "404" or body.get("error") == "not_found"


storage = StorageService()
