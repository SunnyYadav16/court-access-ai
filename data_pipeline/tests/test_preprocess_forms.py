import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dags"))

import src.preprocess_forms as pf

# ══════════════════════════════════════════════════════════════════════════════
# File type detection
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectFileType:
    def test_detects_pdf(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4\n...")
        assert pf._detect_file_type(str(f)) == "pdf"

    def test_detects_html(self, tmp_path):
        f = tmp_path / "test.html"
        f.write_bytes(b"<!DOCTYPE html><html>")
        assert pf._detect_file_type(str(f)) == "html"

    def test_detects_docx_zip(self, tmp_path):
        f = tmp_path / "test.docx"
        f.write_bytes(b"PK\x03\x04...")
        assert pf._detect_file_type(str(f)) == "docx"

    def test_unknown_file_type(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"Just some text")
        assert pf._detect_file_type(str(f)) == "unknown"

    def test_missing_file_returns_none(self):
        assert pf._detect_file_type("/path/does/not/exist") is None


# ══════════════════════════════════════════════════════════════════════════════
# Form name normalization
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeFormName:
    def test_strips_whitespace(self):
        assert pf._normalize_form_name("  My Form  ") == "My Form"

    def test_collapses_multiple_spaces(self):
        assert pf._normalize_form_name("My   Form") == "My Form"

    def test_removes_trailing_extensions(self):
        assert pf._normalize_form_name("My Form.pdf") == "My Form"
        assert pf._normalize_form_name("My Form.docx") == "My Form"
        assert pf._normalize_form_name("My Form.XLSX") == "My Form"

    def test_removes_trailing_hyphens_underscores(self):
        assert pf._normalize_form_name("My Form - ") == "My Form"
        assert pf._normalize_form_name("My Form_") == "My Form"

    def test_handles_empty(self):
        assert pf._normalize_form_name("") == ""
        assert pf._normalize_form_name(None) is None


# ══════════════════════════════════════════════════════════════════════════════
# Slug normalization
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeSlug:
    def test_lowercases_and_replaces_spaces(self):
        assert pf._normalize_slug("My Form Slug") == "my-form-slug"

    def test_replaces_underscores(self):
        assert pf._normalize_slug("my_form_slug") == "my-form-slug"

    def test_removes_special_characters(self):
        assert pf._normalize_slug("my-form-@#$-slug!") == "my-form-slug"

    def test_collapses_hyphens(self):
        assert pf._normalize_slug("my---form--slug") == "my-form-slug"

    def test_strips_trailing_leading_hyphens(self):
        assert pf._normalize_slug("-my-form-") == "my-form"

    def test_handles_empty(self):
        assert pf._normalize_slug("") == ""
        assert pf._normalize_slug(None) is None


# ══════════════════════════════════════════════════════════════════════════════
# run_preprocessing integration
# ══════════════════════════════════════════════════════════════════════════════


class TestRunPreprocessing:
    def test_preprocessing_normalizes_fields(self, tmp_path):
        catalog = [{"form_id": "test-id", "form_name": "  Ugly Name.pdf ", "form_slug": "ugly_slug!", "versions": []}]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        assert catalog[0]["form_name"] == "Ugly Name"
        assert catalog[0]["form_slug"] == "ugly-slug"
        assert report["names_normalized"] == 1
        assert report["slugs_normalized"] == 1

    def test_preprocessing_flags_empty_file(self, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")

        catalog = [{"form_id": "test-id", "form_name": "Test", "versions": [{"file_path_original": str(f)}]}]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        flags = catalog[0].get("preprocessing_flags", [])
        assert "empty_file:EN" in flags
        assert report["empty_files"] == 1

    def test_preprocessing_flags_tiny_file(self, tmp_path):
        f = tmp_path / "tiny.pdf"
        f.write_bytes(b"%PDF-1.4\n...")  # Under 1024 bytes

        catalog = [{"form_id": "test-id", "form_name": "Test", "versions": [{"file_path_original": str(f)}]}]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        flags = catalog[0].get("preprocessing_flags", [])
        assert "tiny_file:EN" in flags
        assert len([i for i in report["issues"] if i["check"] == "tiny_file"]) == 1

    def test_preprocessing_flags_mislabeled_file(self, tmp_path):
        f = tmp_path / "fake.pdf"
        f.write_bytes(b"<!DOCTYPE html>" + b" " * 2000)  # HTML content, over 1024 bytes

        catalog = [{"form_id": "test-id", "form_name": "Test", "versions": [{"file_path_original": str(f)}]}]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        flags = catalog[0].get("preprocessing_flags", [])
        assert "mislabeled:EN:html" in flags
        assert report["mislabeled_files"] == 1

    def test_preprocessing_flags_truncated_pdf(self, tmp_path):
        f = tmp_path / "trunc.pdf"
        f.write_bytes(b"%PDF-1.4\n" + b"x" * 2000)  # Valid magic bytes, >1024 len, but missing %%EOF

        catalog = [{"form_id": "test-id", "form_name": "Test", "versions": [{"file_path_original": str(f)}]}]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        flags = catalog[0].get("preprocessing_flags", [])
        assert "truncated_pdf:EN" in flags
        assert report["corrupt_files"] == 1

    def test_preprocessing_flags_duplicate_hashes(self, tmp_path):
        catalog = [
            {
                "form_id": "id1",
                "content_hash": "hash123",
            },
            {
                "form_id": "id2",
                "content_hash": "hash123",  # Same hash
            },
            {
                "form_id": "id3",
                "content_hash": "hash456",  # Different hash
            },
        ]

        report = pf.run_preprocessing(catalog, str(tmp_path))

        assert report["duplicate_hashes"] == 1
        issues = [i for i in report["issues"] if i["check"] == "duplicate_content"]
        assert len(issues) == 1
        assert "id1" in issues[0]["form_ids"]
        assert "id2" in issues[0]["form_ids"]
