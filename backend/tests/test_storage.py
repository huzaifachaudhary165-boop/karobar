"""File storage: the rules that keep one shop's uploads away from another's.

The Supabase paths are exercised without a network by feeding the helpers the
responses the real service actually returns — including the one that surprised
us: a missing object comes back as HTTP 400 with a 404 inside the body.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.core.errors import BusinessRuleError
from app.services.storage_service import ALLOWED_MIME, StorageService, _is_missing

pytestmark = pytest.mark.asyncio

# A real PNG magic number, so the type check passes and each test can get to the
# part it actually cares about.
PNG = bytes([0x89]) + b"PNG\r\n" + bytes([0x1A]) + b"\n"


def response(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status, text=body, request=httpx.Request("GET", "http://x"))


# ── "not found" detection ────────────────────────────────────────
def test_a_missing_object_is_recognised_despite_the_400_status():
    """Supabase answers a missing object with 400 and puts the 404 in the body.
    Trusting the status line would report "storage is broken" for a file that
    was simply deleted."""
    assert _is_missing(
        response(400, '{"statusCode":"404","error":"not_found","message":"Object not found"}')
    )


def test_a_plain_404_is_still_recognised():
    assert _is_missing(response(404))


def test_a_real_failure_is_not_mistaken_for_a_missing_file():
    assert not _is_missing(response(500, '{"error":"internal"}'))
    assert not _is_missing(response(400, '{"statusCode":"400","error":"invalid_request"}'))
    assert not _is_missing(response(403, "not json at all"))


# ── object keys ──────────────────────────────────────────────────
def test_stored_names_are_prefixed_by_business():
    """The tenant prefix is what makes a bucket listing safe to reason about."""
    service = StorageService()
    assert service._object_url("biz-1/scans/x.png").endswith(
        f"/{settings.SUPABASE_BUCKET}/biz-1/scans/x.png"
    )


def test_a_traversal_key_is_refused_before_it_reaches_supabase():
    service = StorageService()
    with pytest.raises(BusinessRuleError):
        service._object_url("../../other-shop/secret.png")
    with pytest.raises(BusinessRuleError):
        service._object_url("/etc/passwd")


# ── local backend ────────────────────────────────────────────────
async def test_local_save_read_delete_round_trip(tmp_path: Path):
    service = StorageService(base_dir=tmp_path)
    payload = PNG + b"bill"

    saved = await service.save(
        payload, filename="supplier bill.png", business_id="biz-1", folder="scans"
    )
    assert saved["stored_name"].startswith("biz-1/scans/")
    assert saved["url"].startswith("/api/v1/files/"), "downloads must go through our API"
    assert await service.read(saved["stored_name"]) == payload
    assert await service.delete(saved["stored_name"]) is True


async def test_a_filename_cannot_escape_the_storage_root(tmp_path: Path):
    """A traversal attempt that also passes the type check must still be
    defanged — the name is sanitised, not merely rejected later."""
    service = StorageService(base_dir=tmp_path)
    saved = await service.save(
        PNG, filename="../../../etc/passwd.png", business_id="biz-1"
    )
    assert ".." not in saved["stored_name"]
    assert saved["stored_name"].startswith("biz-1/")
    assert (tmp_path / saved["stored_name"]).exists()


async def test_a_file_with_no_recognisable_type_is_refused(tmp_path: Path):
    """Extension-less names never reach the sanitiser: the type check rejects
    them first, which is the outer layer of the same defence."""
    service = StorageService(base_dir=tmp_path)
    with pytest.raises(BusinessRuleError):
        await service.save(b"x", filename="../../../etc/passwd", business_id="biz-1")


async def test_an_oversized_upload_is_rejected_with_the_limit_in_the_message(tmp_path: Path):
    service = StorageService(base_dir=tmp_path)
    too_big = b"x" * ((settings.MAX_UPLOAD_MB + 1) * 1024 * 1024)

    with pytest.raises(BusinessRuleError) as caught:
        await service.save(too_big, filename="huge.png", business_id="biz-1")
    assert str(settings.MAX_UPLOAD_MB) in str(caught.value)


async def test_an_empty_upload_is_rejected(tmp_path: Path):
    service = StorageService(base_dir=tmp_path)
    with pytest.raises(BusinessRuleError):
        await service.save(b"", filename="empty.png", business_id="biz-1")


async def test_an_unsupported_type_is_rejected(tmp_path: Path):
    service = StorageService(base_dir=tmp_path)
    with pytest.raises(BusinessRuleError):
        await service.save(b"MZ", filename="virus.exe", business_id="biz-1")
    assert "application/pdf" in ALLOWED_MIME


# ── backend selection ────────────────────────────────────────────
def test_supabase_is_only_used_when_it_is_actually_configured(monkeypatch):
    """A half-filled .env must fall back to disk rather than failing every
    upload with an auth error."""
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "")
    assert StorageService().backend == "local"

    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "service-role-key")
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://x.supabase.co")
    assert StorageService().backend == "supabase"
