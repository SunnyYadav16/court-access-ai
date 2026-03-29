"""
courtaccess/forms/catalog.py

In-memory catalog lookup helpers used during scraper run processing.
"""


def find_by_url(catalog: list[dict], url: str) -> dict | None:
    """Return the catalog entry whose source_url matches, or None."""
    return next((f for f in catalog if f["source_url"] == url), None)


def find_by_hash(catalog: list[dict], content_hash: str) -> dict | None:
    """Return the first catalog entry whose content_hash matches, or None."""
    return next((f for f in catalog if f["content_hash"] == content_hash), None)


def find_by_id(catalog: list[dict], form_id: str) -> tuple[int, dict]:
    """Return (index, entry) or raise ValueError if form_id not found."""
    for i, entry in enumerate(catalog):
        if entry.get("form_id") == form_id:
            return i, entry
    raise ValueError(f"form_id '{form_id}' not found in catalog.")
