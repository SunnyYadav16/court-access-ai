"""
Shared fixtures for courtaccess/forms/tests.

Sets scraper env vars at module load time so the scraper module can be
imported without crashing on int(None) for the module-level constants.
"""

import os

# Must be set before scraper.py is imported (module-level int() calls).
os.environ.setdefault("SCRAPER_BATCH_SIZE", "10")
os.environ.setdefault("SCRAPER_BATCH_SLEEP_SEC", "5")
os.environ.setdefault("SCRAPER_PRE_DOWNLOAD_SLEEP", "2")
os.environ.setdefault("SCRAPER_REQUEST_TIMEOUT", "30")

import pytest


@pytest.fixture
def sample_catalog():
    """A minimal catalog with two entries for scenario testing."""
    return [
        {
            "form_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "form_name": "Affidavit of Indigency",
            "form_slug": "affidavit-of-indigency",
            "source_url": "https://www.mass.gov/doc/affidavit-of-indigency/download",
            "file_type": "pdf",
            "status": "active",
            "content_hash": "aabbcc001122",
            "current_version": 1,
            "needs_human_review": False,
            "created_at": "2024-01-01T00:00:00+00:00",
            "last_scraped_at": "2024-01-01T00:00:00+00:00",
            "last_updated_at": "2024-01-01T00:00:00+00:00",
            "appearances": [{"division": "District Court", "section_heading": "General"}],
            "versions": [
                {
                    "version": 1,
                    "content_hash": "aabbcc001122",
                    "file_type": "pdf",
                    "file_path_original": "/forms/aaa/v1/affidavit-of-indigency.pdf",
                    "file_path_es": None,
                    "file_path_pt": None,
                    "file_type_es": None,
                    "file_type_pt": None,
                    "created_at": "2024-01-01T00:00:00+00:00",
                }
            ],
        },
        {
            "form_id": "bbbbbbbb-0000-0000-0000-000000000002",
            "form_name": "Civil Complaint",
            "form_slug": "civil-complaint",
            "source_url": "https://www.mass.gov/doc/civil-complaint/download",
            "file_type": "pdf",
            "status": "active",
            "content_hash": "ddeeff334455",
            "current_version": 2,
            "needs_human_review": False,
            "created_at": "2024-01-01T00:00:00+00:00",
            "last_scraped_at": "2024-06-01T00:00:00+00:00",
            "last_updated_at": "2024-06-01T00:00:00+00:00",
            "appearances": [{"division": "Superior Court", "section_heading": "Civil"}],
            "versions": [],
        },
    ]
