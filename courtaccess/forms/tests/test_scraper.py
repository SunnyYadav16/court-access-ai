# """
# courtaccess/forms/tests/test_scraper.py

# Unit tests for courtaccess.forms.scraper.
# Migrated from data_pipeline/tests/test_form_scraper.py.

# Changes from original:
#   - Removed sys.path.insert hack
#   - import src.scrape_forms as sf → import courtaccess.forms.scraper as sf
#   - All mock patch strings updated: "src.scrape_forms.*" → "courtaccess.forms.scraper.*"
# """

# import hashlib
# import uuid
# from pathlib import Path
# from unittest.mock import MagicMock, patch

# import pytest

# import courtaccess.forms.scraper as sf

# # ══════════════════════════════════════════════════════════════════════════════
# # Fixtures & helpers
# # ══════════════════════════════════════════════════════════════════════════════


# @pytest.fixture(autouse=True)
# def tmp_dirs(tmp_path, monkeypatch):
#     """
#     Redirect FORMS_DIR to a temp directory so every test starts with a
#     clean slate and never touches real files.

#     Note: CATALOG_PATH was removed from scraper.py when the module
#     migrated from local JSON storage to DB-backed queries (form_catalog
#     table). Only FORMS_DIR remains as a patchable module-level path.
#     """
#     forms_dir = tmp_path / "forms"
#     forms_dir.mkdir()

#     monkeypatch.setattr(sf, "FORMS_DIR", forms_dir)
#     yield tmp_path


# def _make_pdf(content: str = "fake pdf bytes") -> bytes:
#     return content.encode()


# def _sha256(data: bytes) -> str:
#     return hashlib.sha256(data).hexdigest()


# def _make_catalog_entry(**overrides) -> dict:
#     form_id = str(uuid.uuid4())
#     ts = "2024-01-01T00:00:00+00:00"
#     pdf = b"original bytes"
#     h = _sha256(pdf)
#     base = {
#         "form_id": form_id,
#         "form_name": "Test Form",
#         "form_slug": "test-form",
#         "source_url": "https://www.mass.gov/doc/test-form/download",
#         "file_type": "pdf",
#         "status": "active",
#         "content_hash": h,
#         "current_version": 1,
#         "needs_human_review": True,
#         "created_at": ts,
#         "last_scraped_at": ts,
#         "appearances": [{"division": "District Court", "section_heading": "General"}],
#         "versions": [
#             {
#                 "version": 1,
#                 "content_hash": h,
#                 "file_type": "pdf",
#                 "file_path_original": f"forms/{form_id}/v1/test-form.pdf",
#                 "file_path_es": None,
#                 "file_path_pt": None,
#                 "file_type_es": None,
#                 "file_type_pt": None,
#                 "created_at": ts,
#             }
#         ],
#     }
#     base.update(overrides)
#     return base


# # ══════════════════════════════════════════════════════════════════════════════
# # Catalog helpers
# # ══════════════════════════════════════════════════════════════════════════════


# class TestCatalogHelpers:
#     def test_find_by_url_hit(self):
#         entry = _make_catalog_entry(source_url="https://example.com/a.pdf")
#         found = sf._find_by_url([entry], "https://example.com/a.pdf")
#         assert found is entry

#     def test_find_by_url_miss(self):
#         catalog = [_make_catalog_entry(source_url="https://example.com/a.pdf")]
#         assert sf._find_by_url(catalog, "https://example.com/b.pdf") is None

#     def test_find_by_hash_hit(self):
#         h = _sha256(b"hello")
#         entry = _make_catalog_entry(content_hash=h)
#         assert sf._find_by_hash([entry], h) is entry

#     def test_find_by_hash_miss(self):
#         entry = _make_catalog_entry(content_hash=_sha256(b"hello"))
#         assert sf._find_by_hash([entry], _sha256(b"world")) is None


# # ══════════════════════════════════════════════════════════════════════════════
# # Slug extraction
# # ══════════════════════════════════════════════════════════════════════════════


# class TestSlugFromUrl:
#     def test_standard_download_url(self):
#         assert sf._slug_from_url("https://www.mass.gov/doc/affidavit-of-indigency/download") == "affidavit-of-indigency"

#     def test_url_without_download_suffix(self):
#         assert sf._slug_from_url("https://www.mass.gov/doc/some-form") == "some-form"

#     def test_url_with_trailing_slash(self):
#         assert sf._slug_from_url("https://www.mass.gov/doc/some-form/download/") == "some-form"

#     def test_deeply_nested_url(self):
#         assert sf._slug_from_url("https://www.mass.gov/a/b/c/my-form/download") == "my-form"


# # ══════════════════════════════════════════════════════════════════════════════
# # SHA-256 helper
# # ══════════════════════════════════════════════════════════════════════════════


# class TestSha256:
#     def test_known_value(self):
#         assert sf._sha256(b"") == hashlib.sha256(b"").hexdigest()

#     def test_different_inputs_differ(self):
#         assert sf._sha256(b"a") != sf._sha256(b"b")

#     def test_deterministic(self):
#         assert sf._sha256(b"hello") == sf._sha256(b"hello")


# # ══════════════════════════════════════════════════════════════════════════════
# # File system helpers
# # ══════════════════════════════════════════════════════════════════════════════


# class TestFileHelpers:
#     def test_version_dir_creates_directory(self):
#         d = sf._version_dir("test-id", 1)
#         assert d.exists()
#         assert d.name == "v1"

#     def test_save_original_writes_pdf(self):
#         pdf = _make_pdf("test content")
#         path = sf._save_original("test-id", 1, "my-form", pdf, "pdf")
#         assert Path(path).exists()
#         assert Path(path).read_bytes() == pdf
#         assert path.endswith("my-form.pdf")

#     def test_save_original_writes_docx(self):
#         docx = _make_pdf("docx content")
#         path = sf._save_original("test-id", 1, "my-form", docx, "docx")
#         assert Path(path).exists()
#         assert Path(path).read_bytes() == docx
#         assert path.endswith("my-form.docx")

#     def test_save_original_path_convention(self):
#         path = sf._save_original("abc-123", 2, "some-form", b"data", "pdf")
#         assert "abc-123" in path
#         assert "/v2/" in path
#         assert path.endswith("some-form.pdf")

#     def test_save_translation_spanish(self):
#         pdf = _make_pdf("spanish content")
#         path = sf._save_translation("test-id", 1, "my-form", "es", pdf, "pdf")
#         assert Path(path).exists()
#         assert Path(path).read_bytes() == pdf
#         assert path.endswith("my-form_es.pdf")

#     def test_save_translation_portuguese(self):
#         pdf = _make_pdf("portuguese content")
#         path = sf._save_translation("test-id", 1, "my-form", "pt", pdf, "pdf")
#         assert path.endswith("my-form_pt.pdf")

#     def test_save_translation_docx(self):
#         docx = _make_pdf("docx translation")
#         path = sf._save_translation("test-id", 1, "my-form", "es", docx, "docx")
#         assert path.endswith("my-form_es.docx")

#     def test_save_translation_same_directory_as_original(self):
#         orig = sf._save_original("test-id", 1, "form", b"en", "pdf")
#         es = sf._save_translation("test-id", 1, "form", "es", b"es", "pdf")
#         assert Path(orig).parent == Path(es).parent


# # ══════════════════════════════════════════════════════════════════════════════
# # Appearances helper
# # ══════════════════════════════════════════════════════════════════════════════


# class TestMergeAppearances:
#     def test_adds_new_division(self):
#         entry = _make_catalog_entry(appearances=[{"division": "District Court", "section_heading": "General"}])
#         sf._merge_appearances(entry, [{"division": "Housing Court", "section_heading": "Indigency"}])
#         assert len(entry["appearances"]) == 2

#     def test_skips_duplicate_division(self):
#         entry = _make_catalog_entry(appearances=[{"division": "District Court", "section_heading": "General"}])
#         sf._merge_appearances(entry, [{"division": "District Court", "section_heading": "General"}])
#         assert len(entry["appearances"]) == 1

#     def test_adds_multiple_new_divisions(self):
#         entry = _make_catalog_entry(appearances=[])
#         sf._merge_appearances(
#             entry,
#             [
#                 {"division": "District Court", "section_heading": "General"},
#                 {"division": "Housing Court", "section_heading": "Indigency"},
#                 {"division": "Land Court", "section_heading": "Forms"},
#             ],
#         )
#         assert len(entry["appearances"]) == 3

#     def test_mixed_new_and_existing(self):
#         entry = _make_catalog_entry(appearances=[{"division": "District Court", "section_heading": "General"}])
#         sf._merge_appearances(
#             entry,
#             [
#                 {"division": "District Court", "section_heading": "General"},
#                 {"division": "Housing Court", "section_heading": "Indigency"},
#             ],
#         )
#         assert len(entry["appearances"]) == 2


# # ══════════════════════════════════════════════════════════════════════════════
# # Scenario A — new form
# # ══════════════════════════════════════════════════════════════════════════════


# class TestScenarioA:
#     def test_adds_entry_to_catalog(self):
#         catalog = []
#         queue = []
#         pdf = _make_pdf("new form")
#         apps = [{"division": "District Court", "section_heading": "General"}]
#         sf._handle_new_form(
#             catalog, "New Form", "https://www.mass.gov/doc/new-form/download", pdf, None, None, apps, queue
#         )
#         assert len(catalog) == 1
#         e = catalog[0]
#         assert e["form_name"] == "New Form"
#         assert e["form_slug"] == "new-form"
#         assert e["status"] == "active"
#         assert e["needs_human_review"] is True
#         assert e["content_hash"] == _sha256(pdf)
#         assert e["file_type"] == "pdf"

#     def test_creates_version_entry(self):
#         catalog = []
#         queue = []
#         pdf = _make_pdf("versioned")
#         sf._handle_new_form(catalog, "F", "https://www.mass.gov/doc/f/download", pdf, None, None, [], queue)
#         versions = catalog[0]["versions"]
#         assert len(versions) == 1
#         assert versions[0]["version"] == 1
#         assert versions[0]["file_type"] == "pdf"

#     def test_adds_form_id_to_pretranslation_queue(self):
#         catalog = []
#         queue = []
#         sf._handle_new_form(catalog, "F", "https://www.mass.gov/doc/f/download", _make_pdf(), None, None, [], queue)
#         assert len(queue) == 1
#         assert queue[0] == catalog[0]["form_id"]

#     def test_writes_pdf_to_disk(self):
#         catalog = []
#         queue = []
#         pdf = _make_pdf("disk test")
#         sf._handle_new_form(catalog, "F", "https://www.mass.gov/doc/f/download", pdf, None, None, [], queue)
#         path = catalog[0]["versions"][0]["file_path_original"]
#         assert Path(path).exists()
#         assert Path(path).read_bytes() == pdf

#     def test_writes_docx_to_disk(self):
#         catalog = []
#         queue = []
#         docx = _make_pdf("docx content")
#         sf._handle_new_form(
#             catalog,
#             "F",
#             "https://www.mass.gov/doc/f/download",
#             docx,
#             None,
#             None,
#             [],
#             queue,
#             file_type="docx",
#         )
#         path = catalog[0]["versions"][0]["file_path_original"]
#         assert Path(path).exists()
#         assert path.endswith(".docx")
#         assert catalog[0]["file_type"] == "docx"
#         assert catalog[0]["versions"][0]["file_type"] == "docx"

#     def test_saves_spanish_translation_when_available(self):
#         catalog = []
#         queue = []
#         es_pdf = _make_pdf("spanish")
#         sf._handle_new_form(catalog, "F", "https://www.mass.gov/doc/f/download", _make_pdf(), es_pdf, None, [], queue)
#         es_path = catalog[0]["versions"][0]["file_path_es"]
#         assert es_path is not None
#         assert Path(es_path).exists()

#     def test_translation_paths_null_when_not_available(self):
#         catalog = []
#         queue = []
#         sf._handle_new_form(catalog, "F", "https://www.mass.gov/doc/f/download", _make_pdf(), None, None, [], queue)
#         v = catalog[0]["versions"][0]
#         assert v["file_path_es"] is None
#         assert v["file_path_pt"] is None
#         assert v["file_type_es"] is None
#         assert v["file_type_pt"] is None


# # ══════════════════════════════════════════════════════════════════════════════
# # Scenario B — updated form
# # ══════════════════════════════════════════════════════════════════════════════


# class TestScenarioB:
#     def test_increments_version(self):
#         entry = _make_catalog_entry(current_version=1, content_hash=_sha256(b"old"))
#         new_pdf = _make_pdf("new content")
#         new_hash = _sha256(new_pdf)
#         sf._handle_updated_form(entry, new_pdf, new_hash, None, None, [])
#         assert entry["current_version"] == 2
#         assert entry["content_hash"] == new_hash

#     def test_appends_new_version_at_front(self):
#         entry = _make_catalog_entry(current_version=1)
#         sf._handle_updated_form(entry, _make_pdf("v2"), _sha256(b"v2"), None, None, [])
#         assert len(entry["versions"]) == 2
#         assert entry["versions"][0]["version"] == 2
#         assert entry["versions"][1]["version"] == 1

#     def test_queues_for_pretranslation(self):
#         entry = _make_catalog_entry(current_version=1)
#         queue = []
#         sf._handle_updated_form(entry, _make_pdf(), _sha256(b"x"), None, None, queue)
#         assert entry["form_id"] in queue

#     def test_writes_new_version_to_disk(self):
#         entry = _make_catalog_entry(current_version=1)
#         new_pdf = _make_pdf("v2 on disk")
#         sf._handle_updated_form(entry, new_pdf, _sha256(new_pdf), None, None, [])
#         path = entry["versions"][0]["file_path_original"]
#         assert Path(path).exists()
#         assert "/v2/" in path

#     def test_file_type_updates_on_version(self):
#         entry = _make_catalog_entry(current_version=1, file_type="pdf")
#         new_data = _make_pdf("v2 docx")
#         sf._handle_updated_form(
#             entry,
#             new_data,
#             _sha256(new_data),
#             None,
#             None,
#             [],
#             file_type="docx",
#         )
#         assert entry["file_type"] == "docx"
#         assert entry["versions"][0]["file_type"] == "docx"
#         assert entry["versions"][0]["file_path_original"].endswith(".docx")


# # ══════════════════════════════════════════════════════════════════════════════
# # Scenario C — deleted form (404)
# # ══════════════════════════════════════════════════════════════════════════════


# class TestScenarioC:
#     def test_marks_as_archived(self):
#         entry = _make_catalog_entry(status="active")
#         sf._handle_deleted_form(entry)
#         assert entry["status"] == "archived"

#     def test_updates_last_scraped_at(self):
#         entry = _make_catalog_entry(last_scraped_at="2000-01-01T00:00:00+00:00")
#         sf._handle_deleted_form(entry)
#         assert entry["last_scraped_at"] != "2000-01-01T00:00:00+00:00"

#     def test_preserves_versions(self):
#         entry = _make_catalog_entry()
#         original_versions = list(entry["versions"])
#         sf._handle_deleted_form(entry)
#         assert entry["versions"] == original_versions


# # ══════════════════════════════════════════════════════════════════════════════
# # Scenario D — renamed form
# # ══════════════════════════════════════════════════════════════════════════════


# class TestScenarioD:
#     def test_updates_name(self):
#         entry = _make_catalog_entry(form_name="Old Name")
#         sf._handle_renamed_form(entry, "New Name", entry["source_url"])
#         assert entry["form_name"] == "New Name"

#     def test_updates_url(self):
#         entry = _make_catalog_entry(source_url="https://www.mass.gov/doc/old/download")
#         sf._handle_renamed_form(entry, entry["form_name"], "https://www.mass.gov/doc/new/download")
#         assert entry["source_url"] == "https://www.mass.gov/doc/new/download"

#     def test_updates_slug(self):
#         entry = _make_catalog_entry(form_slug="old-form")
#         sf._handle_renamed_form(entry, "New Form", "https://www.mass.gov/doc/new-form/download")
#         assert entry["form_slug"] == "new-form"


# # ══════════════════════════════════════════════════════════════════════════════
# # Scenario E — no change
# # ══════════════════════════════════════════════════════════════════════════════


# class TestScenarioE:
#     def test_updates_last_scraped_at(self):
#         entry = _make_catalog_entry(last_scraped_at="2000-01-01T00:00:00+00:00")
#         sf._handle_no_change(entry)
#         assert entry["last_scraped_at"] != "2000-01-01T00:00:00+00:00"

#     def test_does_not_change_version(self):
#         entry = _make_catalog_entry(current_version=3)
#         sf._handle_no_change(entry)
#         assert entry["current_version"] == 3

#     def test_does_not_change_status(self):
#         entry = _make_catalog_entry(status="active")
#         sf._handle_no_change(entry)
#         assert entry["status"] == "active"


# # ══════════════════════════════════════════════════════════════════════════════
# # _download_pdf — network behaviour
# # ══════════════════════════════════════════════════════════════════════════════


# class TestDownloadPdf:
#     def test_returns_bytes_on_200(self):
#         mock_resp = MagicMock()
#         mock_resp.status_code = 200
#         mock_resp.content = b"pdf data"
#         with patch("courtaccess.forms.scraper.requests.get", return_value=mock_resp):
#             assert sf._download_pdf("https://example.com/a.pdf") == b"pdf data"

#     def test_returns_none_on_404(self):
#         mock_resp = MagicMock()
#         mock_resp.status_code = 404
#         with patch("courtaccess.forms.scraper.requests.get", return_value=mock_resp):
#             assert sf._download_pdf("https://example.com/a.pdf") is None

#     def test_raises_on_500(self):
#         import requests as req_lib

#         mock_resp = MagicMock()
#         mock_resp.status_code = 500
#         mock_resp.raise_for_status.side_effect = req_lib.exceptions.HTTPError("500 Server Error")
#         with (
#             patch("courtaccess.forms.scraper.requests.get", return_value=mock_resp),
#             pytest.raises(req_lib.exceptions.RequestException),
#         ):
#             sf._download_pdf("https://example.com/a.pdf")

#     def test_raises_on_network_error(self):
#         import requests as req_lib

#         with (
#             patch(
#                 "courtaccess.forms.scraper.requests.get", side_effect=req_lib.exceptions.ConnectionError("no network")
#             ),
#             pytest.raises(req_lib.exceptions.ConnectionError),
#         ):
#             sf._download_pdf("https://example.com/a.pdf")

#     def test_falls_back_to_playwright_on_403(self):
#         mock_resp = MagicMock()
#         mock_resp.status_code = 403
#         with (
#             patch("courtaccess.forms.scraper.requests.get", return_value=mock_resp),
#             patch("courtaccess.forms.scraper._download_pdf_playwright", return_value=b"pw data") as pw_mock,
#         ):
#             result = sf._download_pdf("https://example.com/a.pdf")
#             assert result == b"pw data"
#             pw_mock.assert_called_once()


# # ══════════════════════════════════════════════════════════════════════════════
# # run_scrape — integration-level (all network calls mocked)
# # ══════════════════════════════════════════════════════════════════════════════


# class TestRunScrape:
#     def _run(self, scraped_forms, download_map=None):
#         if download_map is None:
#             download_map = {}

#         def fake_scrape(page_url, division):
#             return scraped_forms

#         def fake_download(url):
#             val = download_map.get(url)
#             if isinstance(val, Exception):
#                 raise val
#             return val

#         with (
#             patch("courtaccess.forms.scraper._scrape_and_download_page", side_effect=fake_scrape),
#             patch("courtaccess.forms.scraper._download_pdf", side_effect=fake_download),
#         ):
#             return sf.run_scrape()

#     def test_new_form_increments_count(self):
#         pdf = _make_pdf("brand new")
#         result = self._run(
#             scraped_forms=[
#                 {
#                     "name": "Form A",
#                     "url": "https://mass.gov/doc/a/download",
#                     "bytes": pdf,
#                     "file_type": "pdf",
#                     "es_bytes": None,
#                     "es_file_type": None,
#                     "pt_bytes": None,
#                     "pt_file_type": None,
#                     "division": "District Court",
#                     "section_heading": "General",
#                 }
#             ]
#         )
#         assert result["counts"]["new"] == 1
#         assert len(result["pretranslation_queue"]) == 1
