"""A file that says nothing about itself is still a file.

Every HTTP client that does not know a file's type announces
`application/octet-stream`. Dio does exactly that — its own docs say
`MultipartFile.fromBytes` "currently defaults to application/octet-stream" — so
every photo the app uploaded arrived declared as an anonymous binary blob and
was refused as an unsupported type. Camera, gallery, everything, silently.

Trusting that header over a filename ending in `.jpg` is the mistake. It means
"no idea", not "binary".
"""

from __future__ import annotations

import pytest

from app.core.errors import BusinessRuleError
from app.services.storage_service import _describe, _resolve_mime, storage

# A one-pixel PNG; small, and genuinely a PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c630001000005000100"
    "0d0a2db40000000049454e44ae426082"
)


@pytest.mark.parametrize("declared", [
    "application/octet-stream",
    "binary/octet-stream",
    "",
    None,
])
def test_a_client_that_does_not_know_is_answered_by_the_filename(declared):
    """The exact shape of the bug: the app said octet-stream for a .jpg."""
    assert _resolve_mime(declared, "bill.jpg") == "image/jpeg"
    assert _resolve_mime(declared, "receipt.pdf") == "application/pdf"


def test_a_client_that_does_know_is_believed():
    assert _resolve_mime("image/png", "whatever.bin") == "image/png"


def test_parameters_on_the_header_are_ignored():
    assert _resolve_mime("image/jpeg; charset=binary", "x.jpg") == "image/jpeg"


def test_case_and_spacing_do_not_matter():
    assert _resolve_mime("  IMAGE/JPEG ", "x.bin") == "image/jpeg"


@pytest.mark.parametrize("filename,expected", [
    ("IMG_0042.HEIC", "image/heic"),
    ("photo.heif", "image/heic"),
    ("scan.jfif", "image/jpeg"),
    ("shot.webp", "image/webp"),
])
def test_phone_camera_formats_are_recognised(filename, expected):
    """heic is what a modern phone saves by default. Miss it and the camera
    button appears broken on exactly the newest devices."""
    assert _resolve_mime(None, filename) == expected


def test_something_genuinely_unknown_stays_unknown():
    assert _resolve_mime(None, "mystery") == "application/octet-stream"
    assert _resolve_mime(None, "app.apk") != "image/jpeg"


@pytest.mark.parametrize("filename", [
    "a.jpg", "a.jpeg", "a.jfif", "a.png", "a.gif", "a.webp", "a.heic",
    "a.heif", "a.pdf", "a.csv", "a.txt", "a.xls", "a.xlsx",
])
def test_every_accepted_extension_resolves_without_asking_the_host(filename):
    """`mimetypes` reads the host's MIME registry, so its answers differ per
    machine: `.webp` returns None on one box, `.csv` comes back as an Excel
    type, and `.xlsx` was unknown on the deployed runtime — which refused a
    spreadsheet with a message saying spreadsheets were fine.

    Whether an upload is accepted must not depend on which computer is serving
    it, so every allowed extension is spelled out rather than looked up.
    """
    from app.services.storage_service import ALLOWED_MIME, _TYPE_BY_SUFFIX

    suffix = filename[filename.rindex("."):]
    assert suffix in _TYPE_BY_SUFFIX, f"{suffix} is not spelled out"
    assert _TYPE_BY_SUFFIX[suffix] in ALLOWED_MIME
    assert _resolve_mime(None, filename) in ALLOWED_MIME


def test_the_table_and_the_allow_list_agree():
    """A type in one and not the other is an upload that fails confusingly."""
    from app.services.storage_service import ALLOWED_MIME, _TYPE_BY_SUFFIX

    unknown = set(_TYPE_BY_SUFFIX.values()) - ALLOWED_MIME
    assert not unknown, f"resolvable but not allowed: {sorted(unknown)}"


# ── the refusal message ──────────────────────────────────────────
def test_the_refusal_names_the_file_not_the_mime_type():
    """"application/x-msdownload is not supported" is not something a
    shopkeeper can act on."""
    message = _describe("virus.exe", "application/x-msdownload")
    assert ".exe" in message

    assert _describe("nameless", "application/octet-stream") == "That file"


# ── end to end ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_photo_uploads_even_when_the_client_says_octet_stream(shop):
    """The whole bug, through the API."""
    client = shop["client"]

    response = await client.post(
        "/files",
        files={"file": ("bill.jpg", PNG, "application/octet-stream")},
        data={"folder": "scans"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_a_photo_with_no_declared_type_at_all_uploads(shop):
    response = await shop["client"].post(
        "/files",
        files={"file": ("receipt.png", PNG)},
        data={"folder": "scans"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_something_that_really_is_not_allowed_is_still_refused(shop):
    """Being forgiving about the header must not make the allow-list toothless."""
    response = await shop["client"].post(
        "/files",
        files={"file": ("installer.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"folder": "scans"},
    )

    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert ".exe" in message, message


@pytest.mark.asyncio
async def test_an_empty_file_is_refused_before_anything_else(shop):
    response = await shop["client"].post(
        "/files",
        files={"file": ("bill.jpg", b"", "image/jpeg")},
        data={"folder": "scans"},
    )
    assert response.status_code == 422


def test_the_stored_type_is_what_gets_saved_not_what_was_claimed():
    """Supabase is sent the resolved type, so a file downloaded later opens as
    the right thing rather than prompting a download."""
    assert _resolve_mime("application/octet-stream", "logo.png") == "image/png"
    assert storage is not None
