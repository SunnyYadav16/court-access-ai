"""
Unit tests for courtaccess/core/validation.py

Functions under test:
  _detect_file_type     — magic byte inspection, missing file, OSError
  _normalize_form_name  — whitespace collapsing, extension stripping
  _normalize_slug       — case, separator, and special-char normalization
  run_preprocessing     — Pass 1 (per-entry) and Pass 2 (cross-entry duplicate)

Design notes:
  - All file I/O uses pytest's tmp_path — no mocking of the filesystem except
    where we explicitly need to simulate an OSError mid-read.
  - Helper writers (_write_valid_pdf etc.) produce files >= MIN_VALID_PDF_SIZE
    so each test isolates exactly one failure mode at a time.
  - MIN_VALID_PDF_SIZE is imported from the module so thresholds stay in sync
    if the env var changes.
"""

from pathlib import Path
from unittest.mock import patch

from courtaccess.core.validation import (
    MIN_VALID_PDF_SIZE,
    _detect_file_type,
    _normalize_form_name,
    _normalize_slug,
    run_preprocessing,
)

# ── Magic byte constants used in test file construction ───────────────────────
PDF_MAGIC = b"%PDF-1.4\n"
DOCX_MAGIC = b"PK\x03\x04"
HTML_START = b"<html><body>"
# UTF-8 BOM followed by <html> — first byte is NOT '<', so the
# `header[:1] == b"<"` branch is skipped. Detection falls through to
# the `b"<html" in header` substring check instead.
BOM_HTML = b"\xef\xbb\xbf<html>"


# ── File-writing helpers ───────────────────────────────────────────────────────


def _write_valid_pdf(path: Path) -> None:
    """Minimal valid PDF: has magic bytes, exceeds size threshold, ends with %%EOF."""
    path.write_bytes(PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE + b"\n%%EOF")


def _write_truncated_pdf(path: Path) -> None:
    """PDF with magic bytes and correct size, but missing %%EOF (truncated download)."""
    path.write_bytes(PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE)


def _write_html_file(path: Path) -> None:
    """HTML content large enough to not trigger the tiny_file check."""
    path.write_bytes(HTML_START + b"x" * MIN_VALID_PDF_SIZE + b"</body></html>")


# ── Catalog entry helpers ──────────────────────────────────────────────────────


def _make_entry(
    form_id: str,
    form_name: str = "Clean Name",
    form_slug: str = "clean-name",
    content_hash: str | None = None,
    versions: list | None = None,
) -> dict:
    """Minimal valid catalog entry."""
    entry: dict = {
        "form_id": form_id,
        "form_name": form_name,
        "form_slug": form_slug,
    }
    if content_hash is not None:
        entry["content_hash"] = content_hash
    if versions is not None:
        entry["versions"] = versions
    return entry


def _make_version(
    path: str | None = None,
    es: str | None = None,
    pt: str | None = None,
) -> dict:
    return {
        "file_path_original": path,
        "file_path_es": es,
        "file_path_pt": pt,
    }


# ─────────────────────────────────────────────────────────────────────────────
# _detect_file_type
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectFileType:
    def test_nonexistent_file_returns_none(self, tmp_path):
        result = _detect_file_type(str(tmp_path / "ghost.pdf"))
        assert result is None

    def test_pdf_magic_bytes_detected(self, tmp_path):
        f = tmp_path / "form.pdf"
        f.write_bytes(PDF_MAGIC + b"some content")
        assert _detect_file_type(str(f)) == "pdf"

    def test_docx_magic_bytes_detected(self, tmp_path):
        f = tmp_path / "form.docx"
        f.write_bytes(DOCX_MAGIC + b"\x00" * 20)
        assert _detect_file_type(str(f)) == "docx"

    def test_zip_magic_bytes_also_returned_as_docx(self, tmp_path):
        # ZIP and DOCX share the same PK magic bytes — both are classified "docx".
        # This is a known limitation of the current two-byte check.
        f = tmp_path / "archive.zip"
        f.write_bytes(DOCX_MAGIC + b"\x00" * 20)
        assert _detect_file_type(str(f)) == "docx"

    def test_html_opening_angle_bracket_detected(self, tmp_path):
        f = tmp_path / "form.html"
        f.write_bytes(HTML_START)
        assert _detect_file_type(str(f)) == "html"

    def test_html_with_utf8_bom_detected_via_substring(self, tmp_path):
        # BOM prefix means header[:1] is \xef, not '<', so the first branch is
        # skipped. The file is still identified as HTML via the '<html' substring.
        f = tmp_path / "bom.html"
        f.write_bytes(BOM_HTML)
        assert _detect_file_type(str(f)) == "html"

    def test_unknown_binary_content_returns_unknown(self, tmp_path):
        f = tmp_path / "mystery.bin"
        f.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07")
        assert _detect_file_type(str(f)) == "unknown"

    def test_empty_file_returns_unknown(self, tmp_path):
        # Empty file: header is b"", no magic bytes match.
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        assert _detect_file_type(str(f)) == "unknown"

    def test_os_error_during_read_returns_none(self, tmp_path):
        f = tmp_path / "unreadable.pdf"
        f.write_bytes(b"irrelevant")
        with patch.object(Path, "read_bytes", side_effect=OSError("permission denied")):
            assert _detect_file_type(str(f)) is None


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_form_name
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeFormName:
    def test_empty_string_returned_unchanged(self):
        assert _normalize_form_name("") == ""

    def test_none_returned_unchanged(self):
        # The function guards with `if not name: return name`
        assert _normalize_form_name(None) is None

    def test_leading_trailing_whitespace_stripped(self):
        assert _normalize_form_name("  Divorce Petition  ") == "Divorce Petition"

    def test_multiple_internal_spaces_collapsed(self):
        assert _normalize_form_name("Child  Support   Form") == "Child Support Form"

    def test_tabs_and_newlines_treated_as_whitespace(self):
        assert _normalize_form_name("Child\tSupport\nForm") == "Child Support Form"

    def test_trailing_pdf_extension_stripped(self):
        assert _normalize_form_name("Divorce Petition.pdf") == "Divorce Petition"

    def test_trailing_pdf_extension_case_insensitive(self):
        assert _normalize_form_name("Divorce Petition.PDF") == "Divorce Petition"

    def test_trailing_docx_extension_stripped(self):
        assert _normalize_form_name("Custody Agreement.docx") == "Custody Agreement"

    def test_trailing_xlsx_extension_stripped(self):
        assert _normalize_form_name("Fee Schedule.xlsx") == "Fee Schedule"

    def test_trailing_doc_extension_stripped(self):
        assert _normalize_form_name("Old Form.doc") == "Old Form"

    def test_extension_in_middle_not_stripped(self):
        # Regex is anchored with $ — only a trailing extension is removed.
        assert _normalize_form_name("form.pdf copy") == "form.pdf copy"

    def test_trailing_junk_stripped_after_extension_removal(self):
        # strip("-_ ") handles both trailing underscores and hyphens left
        # behind after the extension regex removes the .pdf suffix
        assert _normalize_form_name("Form Name_.pdf") == "Form Name"
        assert _normalize_form_name("Form Name-.pdf") == "Form Name"

    def test_already_clean_name_returned_unchanged(self):
        name = "Petition for Guardianship"
        assert _normalize_form_name(name) == name

    def test_whitespace_only_string_returns_empty(self):
        # "   " is truthy so it enters the function, strip() reduces it to ""
        assert _normalize_form_name("   ") == ""


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_slug
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeSlug:
    def test_empty_string_returned_unchanged(self):
        assert _normalize_slug("") == ""

    def test_none_returned_unchanged(self):
        assert _normalize_slug(None) is None

    def test_already_clean_slug_unchanged(self):
        assert _normalize_slug("divorce-petition") == "divorce-petition"

    def test_uppercase_lowercased(self):
        assert _normalize_slug("DivorceForm") == "divorceform"

    def test_underscores_replaced_with_hyphens(self):
        assert _normalize_slug("divorce_petition") == "divorce-petition"

    def test_spaces_replaced_with_hyphens(self):
        assert _normalize_slug("divorce petition") == "divorce-petition"

    def test_multiple_consecutive_hyphens_collapsed(self):
        assert _normalize_slug("divorce--petition") == "divorce-petition"

    def test_leading_hyphens_stripped(self):
        assert _normalize_slug("-divorce-petition") == "divorce-petition"

    def test_trailing_hyphens_stripped(self):
        assert _normalize_slug("divorce-petition-") == "divorce-petition"

    def test_leading_trailing_whitespace_stripped(self):
        assert _normalize_slug("  divorce-petition  ") == "divorce-petition"

    def test_special_characters_removed(self):
        # '@' and '!' are stripped; remaining chars concatenate directly
        assert _normalize_slug("divorce@petition!") == "divorcepetition"

    def test_only_special_characters_returns_empty(self):
        assert _normalize_slug("@#$%^&*") == ""

    def test_mixed_separators_collapsed_to_single_hyphen(self):
        # underscore + space → both become hyphens → collapsed
        assert _normalize_slug("divorce_ petition") == "divorce-petition"

    def test_mixed_case_underscores_and_spaces(self):
        assert _normalize_slug("Divorce_Petition Form") == "divorce-petition-form"

    def test_numbers_preserved(self):
        assert _normalize_slug("form-cj-d-301") == "form-cj-d-301"


# ─────────────────────────────────────────────────────────────────────────────
# run_preprocessing — Pass 1 (per-entry checks)
# ─────────────────────────────────────────────────────────────────────────────


class TestRunPreprocessingPass1:
    def test_empty_catalog_returns_all_zero_report(self, tmp_path):
        report = run_preprocessing([], str(tmp_path))
        assert report["total_processed"] == 0
        assert report["names_normalized"] == 0
        assert report["slugs_normalized"] == 0
        assert report["mislabeled_files"] == 0
        assert report["empty_files"] == 0
        assert report["corrupt_files"] == 0
        assert report["duplicate_hashes"] == 0
        assert report["issues"] == []

    def test_total_processed_counts_all_entries(self, tmp_path):
        catalog = [_make_entry("form-1"), _make_entry("form-2"), _make_entry("form-3")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["total_processed"] == 3

    def test_clean_entry_with_no_versions_produces_no_flags(self, tmp_path):
        # NOTE: when an entry has no versions, the loop hits `continue` before
        # the `del entry["preprocessing_flags"]` cleanup line at the bottom.
        # The key is left as an empty list []. This differs from entries that
        # DO have versions and pass all checks (those get the key deleted).
        catalog = [_make_entry("form-1")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["names_normalized"] == 0
        assert report["empty_files"] == 0
        assert report["issues"] == []
        assert catalog[0].get("preprocessing_flags") == []

    # ── Name normalization ────────────────────────────────────────────────────

    def test_dirty_name_normalized_in_place(self, tmp_path):
        catalog = [_make_entry("form-1", form_name="  Dirty  Name  ")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert catalog[0]["form_name"] == "Dirty Name"
        assert report["names_normalized"] == 1

    def test_clean_name_not_counted_as_normalized(self, tmp_path):
        catalog = [_make_entry("form-1", form_name="Clean Name")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["names_normalized"] == 0

    # ── Slug normalization ────────────────────────────────────────────────────

    def test_dirty_slug_normalized_in_place(self, tmp_path):
        catalog = [_make_entry("form-1", form_slug="Dirty_Slug Here")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert catalog[0]["form_slug"] == "dirty-slug-here"
        assert report["slugs_normalized"] == 1

    def test_clean_slug_not_counted_as_normalized(self, tmp_path):
        catalog = [_make_entry("form-1", form_slug="clean-slug")]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["slugs_normalized"] == 0

    # ── File path resolution ──────────────────────────────────────────────────

    def test_missing_file_path_value_skipped(self, tmp_path):
        # file_path_original=None means nothing to check
        versions = [_make_version(path=None)]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["issues"] == []

    def test_nonexistent_file_on_disk_skipped(self, tmp_path):
        # A path that doesn't exist is silently skipped (validate_catalog handles it)
        versions = [_make_version(path=str(tmp_path / "ghost.pdf"))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["issues"] == []

    # ── Empty file ────────────────────────────────────────────────────────────

    def test_empty_file_increments_empty_files_counter(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["empty_files"] == 1

    def test_empty_file_adds_flag_to_entry(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        run_preprocessing(catalog, str(tmp_path))
        assert "empty_file:EN" in catalog[0]["preprocessing_flags"]

    def test_empty_file_adds_issue_with_correct_fields(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        issue = next(i for i in report["issues"] if i["check"] == "empty_file")
        assert issue["form_id"] == "form-1"
        assert issue["file"] == str(f)

    def test_empty_file_skips_type_and_integrity_checks(self, tmp_path):
        # After flagging empty file the code does `continue` — mislabeled and
        # corrupt counters must remain at zero.
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["mislabeled_files"] == 0
        assert report["corrupt_files"] == 0

    # ── Tiny file ─────────────────────────────────────────────────────────────

    def test_tiny_file_adds_issue_but_has_no_dedicated_counter(self, tmp_path):
        # IMPORTANT: tiny_file has no report["tiny_files"] key.
        # It only appears in the issues list. This is intentional.
        f = tmp_path / "tiny.pdf"
        # Small but valid PDF — has %%EOF so only tiny_file triggers, not truncated
        f.write_bytes(b"%PDF-1.4\n%%EOF")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert "tiny_files" not in report
        assert any(i["check"] == "tiny_file" for i in report["issues"])
        assert report["empty_files"] == 0

    def test_tiny_file_does_not_stop_further_checks(self, tmp_path):
        # tiny_file does NOT do `continue` — type and integrity checks still run.
        # A tiny file with no %%EOF gets BOTH tiny_file and truncated_pdf issues.
        f = tmp_path / "tiny_truncated.pdf"
        f.write_bytes(b"%PDF-1.4\nno eof here")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        checks = {i["check"] for i in report["issues"]}
        assert "tiny_file" in checks
        assert "truncated_pdf" in checks

    # ── Mislabeled file ───────────────────────────────────────────────────────

    def test_mislabeled_file_increments_mislabeled_counter(self, tmp_path):
        f = tmp_path / "mislabeled.pdf"
        _write_html_file(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["mislabeled_files"] == 1

    def test_mislabeled_file_adds_correct_flag(self, tmp_path):
        f = tmp_path / "mislabeled.pdf"
        _write_html_file(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        run_preprocessing(catalog, str(tmp_path))
        assert "mislabeled:EN:html" in catalog[0]["preprocessing_flags"]

    def test_mislabeled_file_issue_has_correct_expected_and_actual(self, tmp_path):
        f = tmp_path / "mislabeled.pdf"
        _write_html_file(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        issue = next(i for i in report["issues"] if i["check"] == "mislabeled_file")
        assert issue["expected"] == "pdf"
        assert issue["actual"] == "html"

    # ── Valid PDF ─────────────────────────────────────────────────────────────

    def test_valid_pdf_produces_no_flags_or_issues(self, tmp_path):
        f = tmp_path / "valid.pdf"
        _write_valid_pdf(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["corrupt_files"] == 0
        assert report["mislabeled_files"] == 0
        assert report["empty_files"] == 0
        assert report["issues"] == []

    # ── Truncated PDF ─────────────────────────────────────────────────────────

    def test_truncated_pdf_increments_corrupt_counter(self, tmp_path):
        f = tmp_path / "truncated.pdf"
        _write_truncated_pdf(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["corrupt_files"] == 1

    def test_truncated_pdf_adds_correct_flag(self, tmp_path):
        f = tmp_path / "truncated.pdf"
        _write_truncated_pdf(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        run_preprocessing(catalog, str(tmp_path))
        assert "truncated_pdf:EN" in catalog[0]["preprocessing_flags"]

    def test_truncated_pdf_adds_issue_with_correct_check(self, tmp_path):
        f = tmp_path / "truncated.pdf"
        _write_truncated_pdf(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))
        assert any(i["check"] == "truncated_pdf" for i in report["issues"])

    # ── Unreadable PDF (OSError on full read) ─────────────────────────────────

    def test_unreadable_pdf_increments_corrupt_counter(self, tmp_path):
        # _detect_file_type reads first 8 bytes (returns "pdf").
        # The integrity check then calls read_bytes() again — that one raises.
        f = tmp_path / "unreadable.pdf"
        f.write_bytes(PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        side_effects = [
            PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE,  # _detect_file_type read
            OSError("disk error"),  # integrity check read
        ]
        with patch.object(Path, "read_bytes", side_effect=side_effects):
            report = run_preprocessing(catalog, str(tmp_path))
        assert report["corrupt_files"] == 1

    def test_unreadable_pdf_adds_correct_flag(self, tmp_path):
        f = tmp_path / "unreadable.pdf"
        f.write_bytes(PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        side_effects = [
            PDF_MAGIC + b"x" * MIN_VALID_PDF_SIZE,
            OSError("disk error"),
        ]
        with patch.object(Path, "read_bytes", side_effect=side_effects):
            run_preprocessing(catalog, str(tmp_path))
        assert "unreadable:EN" in catalog[0]["preprocessing_flags"]

    # ── preprocessing_flags key lifecycle ────────────────────────────────────

    def test_clean_entry_has_no_preprocessing_flags_key(self, tmp_path):
        # When no flags are added, the key is deleted entirely (not left as []).
        f = tmp_path / "clean.pdf"
        _write_valid_pdf(f)
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        run_preprocessing(catalog, str(tmp_path))
        assert "preprocessing_flags" not in catalog[0]

    def test_flagged_entry_retains_preprocessing_flags_key(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        versions = [_make_version(path=str(f))]
        catalog = [_make_entry("form-1", versions=versions)]
        run_preprocessing(catalog, str(tmp_path))
        assert "preprocessing_flags" in catalog[0]
        assert len(catalog[0]["preprocessing_flags"]) > 0

    # ── All three file keys (EN / ES / PT) ───────────────────────────────────

    def test_all_three_language_file_keys_checked_independently(self, tmp_path):
        en = tmp_path / "en.pdf"
        _write_valid_pdf(en)
        es = tmp_path / "es.pdf"
        es.write_bytes(b"")  # empty → empty_file:ES
        pt = tmp_path / "pt.pdf"
        _write_html_file(pt)  # HTML content → mislabeled:PT:html

        versions = [_make_version(path=str(en), es=str(es), pt=str(pt))]
        catalog = [_make_entry("form-1", versions=versions)]
        report = run_preprocessing(catalog, str(tmp_path))

        flags = catalog[0]["preprocessing_flags"]
        assert "empty_file:ES" in flags
        assert "mislabeled:PT:html" in flags
        # EN was clean — no EN flag
        assert not any("EN" in f for f in flags)
        assert report["empty_files"] == 1
        assert report["mislabeled_files"] == 1

    def test_multiple_entries_counters_sum_across_entries(self, tmp_path):
        f1 = tmp_path / "empty1.pdf"
        f1.write_bytes(b"")
        f2 = tmp_path / "empty2.pdf"
        f2.write_bytes(b"")
        catalog = [
            _make_entry("form-1", versions=[_make_version(str(f1))]),
            _make_entry("form-2", versions=[_make_version(str(f2))]),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["total_processed"] == 2
        assert report["empty_files"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# run_preprocessing — Pass 2 (cross-entry duplicate detection)
# ─────────────────────────────────────────────────────────────────────────────


class TestRunPreprocessingPass2:
    def test_unique_hashes_produce_no_duplicates(self, tmp_path):
        catalog = [
            _make_entry("form-1", content_hash="aaa"),
            _make_entry("form-2", content_hash="bbb"),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 0

    def test_two_forms_sharing_hash_detected(self, tmp_path):
        catalog = [
            _make_entry("form-1", content_hash="shared"),
            _make_entry("form-2", content_hash="shared"),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 1

    def test_duplicate_issue_lists_all_conflicting_form_ids(self, tmp_path):
        catalog = [
            _make_entry("form-1", content_hash="shared"),
            _make_entry("form-2", content_hash="shared"),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        issue = next(i for i in report["issues"] if i["check"] == "duplicate_content")
        assert set(issue["form_ids"]) == {"form-1", "form-2"}

    def test_three_way_duplicate_counted_once_not_three(self, tmp_path):
        # Three forms sharing one hash = one collision event, not three.
        # duplicate_hashes counts unique hashes that have collisions.
        catalog = [
            _make_entry("form-1", content_hash="shared"),
            _make_entry("form-2", content_hash="shared"),
            _make_entry("form-3", content_hash="shared"),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 1
        issue = next(i for i in report["issues"] if i["check"] == "duplicate_content")
        assert len(issue["form_ids"]) == 3

    def test_two_separate_collision_groups_both_counted(self, tmp_path):
        catalog = [
            _make_entry("form-1", content_hash="hash-a"),
            _make_entry("form-2", content_hash="hash-a"),
            _make_entry("form-3", content_hash="hash-b"),
            _make_entry("form-4", content_hash="hash-b"),
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 2

    def test_entry_without_content_hash_excluded_from_duplicate_check(self, tmp_path):
        # Entries with no content_hash key cannot participate in duplicate detection.
        catalog = [
            _make_entry("form-1"),  # no content_hash
            _make_entry("form-2"),  # no content_hash
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 0

    def test_entry_without_form_id_excluded_from_duplicate_check(self, tmp_path):
        # The check requires both content_hash AND form_id to be present.
        catalog = [
            {"form_name": "No ID A", "content_hash": "same"},
            {"form_name": "No ID B", "content_hash": "same"},
        ]
        report = run_preprocessing(catalog, str(tmp_path))
        assert report["duplicate_hashes"] == 0
