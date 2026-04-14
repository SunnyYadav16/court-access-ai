"""
Tests for courtaccess/forms/scraper.py

Covers all pure helper functions and the five scenario handlers.
Network calls (Playwright, requests) are mocked out.
"""

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from unittest.mock import patch

from courtaccess.forms.scraper import (
    _find_by_hash,
    _find_by_url,
    _handle_deleted_form,
    _handle_new_form,
    _handle_no_change,
    _handle_renamed_form,
    _handle_updated_form,
    _is_docx,
    _merge_appearances,
    _now,
    _save_original,
    _save_translation,
    _sha256,
    _slug_from_url,
    _version_dir,
)

# ══════════════════════════════════════════════════════════════════════════════
# _now
# ══════════════════════════════════════════════════════════════════════════════


def test_now_returns_string():
    result = _now()
    assert isinstance(result, str)


def test_now_is_valid_iso8601():
    result = _now()
    # Should parse without raising
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


def test_now_is_utc():
    result = _now()
    parsed = datetime.fromisoformat(result)
    assert parsed.utcoffset().total_seconds() == 0


# ══════════════════════════════════════════════════════════════════════════════
# _sha256
# ══════════════════════════════════════════════════════════════════════════════


def test_sha256_known_value():
    data = b"hello"
    expected = hashlib.sha256(b"hello").hexdigest()
    assert _sha256(data) == expected


def test_sha256_empty_bytes():
    result = _sha256(b"")
    assert len(result) == 64  # SHA-256 hex is always 64 chars


def test_sha256_different_inputs_differ():
    assert _sha256(b"abc") != _sha256(b"xyz")


def test_sha256_same_input_stable():
    assert _sha256(b"stable") == _sha256(b"stable")


# ══════════════════════════════════════════════════════════════════════════════
# _slug_from_url
# ══════════════════════════════════════════════════════════════════════════════


def test_slug_from_url_with_download_suffix():
    url = "https://www.mass.gov/doc/affidavit-of-indigency/download"
    assert _slug_from_url(url) == "affidavit-of-indigency"


def test_slug_from_url_without_download_suffix():
    url = "https://www.mass.gov/doc/civil-complaint"
    assert _slug_from_url(url) == "civil-complaint"


def test_slug_from_url_trailing_slash():
    url = "https://www.mass.gov/doc/motion-to-dismiss/download/"
    assert _slug_from_url(url) == "motion-to-dismiss"


def test_slug_from_url_simple_path():
    url = "https://www.mass.gov/some-form"
    assert _slug_from_url(url) == "some-form"


def test_slug_from_url_preserves_hyphens():
    url = "https://www.mass.gov/doc/restraining-order-extension/download"
    assert _slug_from_url(url) == "restraining-order-extension"


# ══════════════════════════════════════════════════════════════════════════════
# _is_docx
# ══════════════════════════════════════════════════════════════════════════════


def _make_docx_bytes() -> bytes:
    """Create a minimal valid DOCX (ZIP with word/document.xml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


def _make_plain_zip_bytes() -> bytes:
    """Create a ZIP with no word/ directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.txt", "not a docx")
    return buf.getvalue()


def test_is_docx_valid_docx():
    assert _is_docx(_make_docx_bytes()) is True


def test_is_docx_plain_zip_is_false():
    assert _is_docx(_make_plain_zip_bytes()) is False


def test_is_docx_pdf_magic_bytes():
    pdf_bytes = b"%PDF-1.4 ..." + b"\x00" * 100
    assert _is_docx(pdf_bytes) is False


def test_is_docx_empty_bytes():
    assert _is_docx(b"") is False


def test_is_docx_too_short():
    assert _is_docx(b"PK") is False


def test_is_docx_random_bytes():
    assert _is_docx(b"\x00\x01\x02\x03" * 10) is False


# ══════════════════════════════════════════════════════════════════════════════
# _find_by_url
# ══════════════════════════════════════════════════════════════════════════════


def test_find_by_url_found(sample_catalog):
    result = _find_by_url(sample_catalog, "https://www.mass.gov/doc/affidavit-of-indigency/download")
    assert result is not None
    assert result["form_name"] == "Affidavit of Indigency"


def test_find_by_url_not_found(sample_catalog):
    result = _find_by_url(sample_catalog, "https://www.mass.gov/doc/nonexistent/download")
    assert result is None


def test_find_by_url_empty_catalog():
    result = _find_by_url([], "https://www.mass.gov/doc/anything/download")
    assert result is None


def test_find_by_url_returns_first_match():
    catalog = [
        {"source_url": "https://example.com/a", "form_name": "First"},
        {"source_url": "https://example.com/a", "form_name": "Second"},
    ]
    result = _find_by_url(catalog, "https://example.com/a")
    assert result["form_name"] == "First"


# ══════════════════════════════════════════════════════════════════════════════
# _find_by_hash
# ══════════════════════════════════════════════════════════════════════════════


def test_find_by_hash_found(sample_catalog):
    result = _find_by_hash(sample_catalog, "aabbcc001122")
    assert result is not None
    assert result["form_name"] == "Affidavit of Indigency"


def test_find_by_hash_not_found(sample_catalog):
    result = _find_by_hash(sample_catalog, "000000000000")
    assert result is None


def test_find_by_hash_empty_catalog():
    result = _find_by_hash([], "abc123")
    assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# _merge_appearances
# ══════════════════════════════════════════════════════════════════════════════


def test_merge_appearances_adds_new_division():
    entry = {"form_name": "Test Form", "appearances": [{"division": "District Court", "section_heading": "A"}]}
    new_apps = [{"division": "Superior Court", "section_heading": "B"}]
    _merge_appearances(entry, new_apps)
    assert len(entry["appearances"]) == 2
    divisions = {a["division"] for a in entry["appearances"]}
    assert "Superior Court" in divisions


def test_merge_appearances_skips_duplicate_division():
    entry = {"form_name": "Test Form", "appearances": [{"division": "District Court", "section_heading": "A"}]}
    new_apps = [{"division": "District Court", "section_heading": "Different heading"}]
    _merge_appearances(entry, new_apps)
    assert len(entry["appearances"]) == 1


def test_merge_appearances_empty_new_list():
    entry = {"form_name": "Test Form", "appearances": [{"division": "District Court", "section_heading": "A"}]}
    _merge_appearances(entry, [])
    assert len(entry["appearances"]) == 1


def test_merge_appearances_multiple_new():
    entry = {"form_name": "Test Form", "appearances": []}
    new_apps = [
        {"division": "Housing Court", "section_heading": "X"},
        {"division": "Juvenile Court", "section_heading": "Y"},
        {"division": "Housing Court", "section_heading": "Duplicate"},
    ]
    _merge_appearances(entry, new_apps)
    assert len(entry["appearances"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Scenario handlers
# ══════════════════════════════════════════════════════════════════════════════


def test_handle_deleted_form_sets_archived():
    entry = {"form_name": "Old Form", "form_id": "abc", "status": "active", "last_scraped_at": "old"}
    _handle_deleted_form(entry)
    assert entry["status"] == "archived"


def test_handle_deleted_form_updates_last_scraped_at():
    entry = {"form_name": "Old Form", "form_id": "abc", "status": "active", "last_scraped_at": "old"}
    before = datetime.now(UTC)
    _handle_deleted_form(entry)
    after = datetime.now(UTC)
    ts = datetime.fromisoformat(entry["last_scraped_at"])
    assert before <= ts <= after


def test_handle_renamed_form_updates_name():
    entry = {
        "form_name": "Old Name",
        "form_slug": "old-name",
        "source_url": "https://www.mass.gov/doc/old-name/download",
        "last_scraped_at": "old",
    }
    _handle_renamed_form(entry, "New Name", "https://www.mass.gov/doc/new-name/download")
    assert entry["form_name"] == "New Name"


def test_handle_renamed_form_updates_slug():
    entry = {
        "form_name": "Old Name",
        "form_slug": "old-name",
        "source_url": "https://www.mass.gov/doc/old-name/download",
        "last_scraped_at": "old",
    }
    _handle_renamed_form(entry, "New Name", "https://www.mass.gov/doc/new-name/download")
    assert entry["form_slug"] == "new-name"


def test_handle_renamed_form_updates_source_url():
    new_url = "https://www.mass.gov/doc/new-name/download"
    entry = {
        "form_name": "Old Name",
        "form_slug": "old-name",
        "source_url": "https://www.mass.gov/doc/old-name/download",
        "last_scraped_at": "old",
    }
    _handle_renamed_form(entry, "New Name", new_url)
    assert entry["source_url"] == new_url


def test_handle_no_change_updates_last_scraped_at():
    entry = {"form_name": "Form", "last_scraped_at": "2020-01-01T00:00:00+00:00"}
    before = datetime.now(UTC)
    _handle_no_change(entry)
    after = datetime.now(UTC)
    ts = datetime.fromisoformat(entry["last_scraped_at"])
    assert before <= ts <= after


def test_handle_no_change_does_not_modify_other_fields():
    entry = {
        "form_name": "Stable Form",
        "form_slug": "stable-form",
        "status": "active",
        "content_hash": "abc123",
        "last_scraped_at": "old",
    }
    _handle_no_change(entry)
    assert entry["form_name"] == "Stable Form"
    assert entry["status"] == "active"
    assert entry["content_hash"] == "abc123"


def test_handle_new_form_adds_to_catalog(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    catalog = []
    queue = []
    raw = b"%PDF-1.4 fake pdf content"
    url = "https://www.mass.gov/doc/test-form/download"

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        _handle_new_form(
            catalog,
            "Test Form",
            url,
            raw,
            None,
            None,
            [{"division": "District Court", "section_heading": "General"}],
            queue,
        )

    assert len(catalog) == 1
    assert len(queue) == 1
    entry = catalog[0]
    assert entry["form_name"] == "Test Form"
    assert entry["source_url"] == url
    assert entry["status"] == "active"
    assert entry["needs_human_review"] is True
    assert entry["current_version"] == 1
    assert len(entry["versions"]) == 1
    assert entry["form_id"] == queue[0]


def test_handle_new_form_saves_translations(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    catalog = []
    queue = []
    raw = b"%PDF-1.4 fake pdf content"
    es_bytes = b"%PDF-1.4 spanish"
    pt_bytes = b"%PDF-1.4 portuguese"

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        _handle_new_form(
            catalog,
            "Test Form",
            "https://www.mass.gov/doc/test-form/download",
            raw,
            es_bytes,
            pt_bytes,
            [],
            queue,
        )

    entry = catalog[0]
    version = entry["versions"][0]
    assert version["file_path_es"] is not None
    assert version["file_path_pt"] is not None


def test_handle_new_form_no_translations_saves_none(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    catalog = []
    queue = []
    raw = b"%PDF-1.4 fake"

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        _handle_new_form(
            catalog,
            "No Trans Form",
            "https://www.mass.gov/doc/no-trans/download",
            raw,
            None,
            None,
            [],
            queue,
        )

    version = catalog[0]["versions"][0]
    assert version["file_path_es"] is None
    assert version["file_path_pt"] is None


def test_handle_updated_form_increments_version(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    entry = {
        "form_id": "test-id-001",
        "form_name": "Some Form",
        "form_slug": "some-form",
        "current_version": 1,
        "content_hash": "oldhash",
        "file_type": "pdf",
        "status": "active",
        "needs_human_review": False,
        "last_scraped_at": "old",
        "last_updated_at": "old",
        "versions": [],
    }
    queue = []
    new_bytes = b"%PDF new content"
    new_hash = _sha256(new_bytes)

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        _handle_updated_form(entry, new_bytes, new_hash, None, None, queue)

    assert entry["current_version"] == 2
    assert entry["content_hash"] == new_hash
    assert entry["needs_human_review"] is True
    assert entry["status"] == "active"
    assert len(entry["versions"]) == 1
    assert entry["versions"][0]["version"] == 2
    assert entry["form_id"] in queue


def test_handle_updated_form_inserts_version_at_front(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    existing_version = {
        "version": 1,
        "content_hash": "oldhash",
        "file_type": "pdf",
        "file_path_original": "/old/path.pdf",
        "file_path_es": None,
        "file_path_pt": None,
        "file_type_es": None,
        "file_type_pt": None,
        "created_at": "2024-01-01T00:00:00+00:00",
    }
    entry = {
        "form_id": "test-id-002",
        "form_name": "Form",
        "form_slug": "form",
        "current_version": 1,
        "content_hash": "oldhash",
        "file_type": "pdf",
        "status": "active",
        "needs_human_review": False,
        "last_scraped_at": "old",
        "last_updated_at": "old",
        "versions": [existing_version],
    }
    queue = []

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        _handle_updated_form(entry, b"new bytes", "newhash", None, None, queue)

    # Newest version is at index 0
    assert entry["versions"][0]["version"] == 2
    assert entry["versions"][1]["version"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Filesystem helpers
# ══════════════════════════════════════════════════════════════════════════════


def test_version_dir_creates_directory(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        d = _version_dir("my-form-id", 3)

    assert d.exists()
    assert d.is_dir()
    assert d == tmp_path / "my-form-id" / "v3"


def test_version_dir_idempotent(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        d1 = _version_dir("form-id", 1)
        d2 = _version_dir("form-id", 1)

    assert d1 == d2


def test_save_original_writes_pdf(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    raw = b"%PDF-1.4 content"
    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        path = _save_original("fid-001", 1, "my-form", raw, "pdf")

    assert path.endswith(".pdf")
    assert (tmp_path / "fid-001" / "v1" / "my-form.pdf").read_bytes() == raw


def test_save_original_writes_docx(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    raw = b"PK\x03\x04 fake docx"
    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        path = _save_original("fid-002", 1, "my-form", raw, "docx")

    assert path.endswith(".docx")
    assert (tmp_path / "fid-002" / "v1" / "my-form.docx").read_bytes() == raw


def test_save_original_unknown_type_defaults_to_pdf(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    raw = b"some data"
    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        path = _save_original("fid-003", 1, "my-form", raw, "html")

    assert path.endswith(".pdf")


def test_save_translation_writes_es(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    raw = b"%PDF-1.4 spanish"
    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        path = _save_translation("fid-004", 1, "my-form", "es", raw, "pdf")

    assert path.endswith("_es.pdf")
    assert (tmp_path / "fid-004" / "v1" / "my-form_es.pdf").read_bytes() == raw


def test_save_translation_writes_pt(tmp_path):
    from courtaccess.forms import scraper as scraper_mod

    raw = b"%PDF-1.4 portuguese"
    with patch.object(scraper_mod, "FORMS_DIR", tmp_path):
        path = _save_translation("fid-005", 1, "my-form", "pt", raw, "pdf")

    assert path.endswith("_pt.pdf")
