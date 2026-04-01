"""
courtaccess/core/validation.py

File-level and form-data validation for the preprocessing pipeline.
Migrated from data_pipeline/dags/src/preprocess_forms.py.

Validation steps:
  1. File type detection   — verify .pdf files are actually PDFs (magic bytes)
  2. PDF integrity         — check files can be opened (not corrupt/truncated)
  3. Empty file removal    — flag 0-byte or near-empty downloads
  4. Form name cleanup     — trim whitespace, normalize casing
  5. Slug normalization    — ensure clean URL-safe slugs
  6. Duplicate detection   — flag different form_ids with identical content_hash
"""

import logging
import re
from pathlib import Path

from courtaccess.core.config import settings

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

# ── File type magic bytes ─────────────────────────────────────────────────────
MAGIC_BYTES = {
    "pdf": b"%PDF",
    "html": b"<",
    "docx": b"PK",
    "zip": b"PK",
}

# ── Thresholds ────────────────────────────────────────────────────────────────
MIN_VALID_PDF_SIZE = settings.anomaly_min_pdf_size_bytes


def _detect_file_type(file_path: str) -> str | None:
    """
    Read the first 8 bytes of a file and determine its actual type.
    Returns: 'pdf', 'html', 'docx', or 'unknown'.
    """
    p = Path(file_path)
    if not p.exists():
        return None

    try:
        header = p.read_bytes()[:8]
    except OSError:
        return None

    if header[:4] == MAGIC_BYTES["pdf"]:
        return "pdf"
    if header[:2] == MAGIC_BYTES["docx"]:
        return "docx"
    if header[:1] == MAGIC_BYTES["html"] or b"<!DOCTYPE" in header or b"<html" in header:
        return "html"
    return "unknown"


def _normalize_form_name(name: str) -> str:
    """
    Clean up a form name:
      - Strip leading/trailing whitespace
      - Collapse multiple spaces into one
      - Strip trailing file extensions that leaked into names
    """
    if not name:
        return name

    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\.(pdf|docx|xlsx|doc)$", "", name, flags=re.IGNORECASE)
    name = name.strip("-_ ")

    return name


def _normalize_slug(slug: str) -> str:
    """
    Clean up a slug:
      - Lowercase
      - Replace underscores and spaces with hyphens
      - Collapse multiple hyphens
      - Strip leading/trailing hyphens
      - Remove non-alphanumeric characters except hyphens
    """
    if not slug:
        return slug

    slug = slug.lower().strip()
    slug = slug.replace("_", "-").replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")

    return slug


def run_preprocessing(catalog: list[dict], forms_dir: str) -> dict:
    """
    Run all preprocessing steps on the catalog and downloaded files.

    Args:
        catalog:   The full form catalog (list of dicts, loaded from JSON).
        forms_dir: Path to the forms/ directory containing downloaded PDFs.

    Returns:
        A report dict with counts and details of each preprocessing action.

    Modifies catalog entries in-place:
        - Normalizes form_name and form_slug
        - Adds 'preprocessing_flags' list to each entry
    """
    report = {
        "total_processed": 0,
        "names_normalized": 0,
        "slugs_normalized": 0,
        "mislabeled_files": 0,
        "empty_files": 0,
        "corrupt_files": 0,
        "duplicate_hashes": 0,
        "issues": [],
    }

    # ══════════════════════════════════════════════════════════════════════════
    # Pass 1: Per-entry preprocessing
    # ══════════════════════════════════════════════════════════════════════════

    for entry in catalog:
        report["total_processed"] += 1
        entry.setdefault("preprocessing_flags", [])
        flags = entry["preprocessing_flags"]
        form_id = entry.get("form_id", "?")
        form_name = entry.get("form_name", "")

        # ── 1. Form name normalization ────────────────────────────────────────
        cleaned_name = _normalize_form_name(form_name)
        if cleaned_name != form_name:
            logger.info(
                "Name normalized: '%s' → '%s' (form_id=%s)",
                form_name,
                cleaned_name,
                form_id,
            )
            entry["form_name"] = cleaned_name
            report["names_normalized"] += 1

        # ── 2. Slug normalization ─────────────────────────────────────────────
        slug = entry.get("form_slug", "")
        cleaned_slug = _normalize_slug(slug)
        if cleaned_slug != slug:
            logger.info(
                "Slug normalized: '%s' → '%s' (form_id=%s)",
                slug,
                cleaned_slug,
                form_id,
            )
            entry["form_slug"] = cleaned_slug
            report["slugs_normalized"] += 1

        # ── 3. File checks on latest version ───────────────────────────
        versions = entry.get("versions", [])
        if not versions:
            continue

        latest = versions[0]
        for file_key, lang_label in [
            ("file_path_original", "EN"),
            ("file_path_es", "ES"),
            ("file_path_pt", "PT"),
        ]:
            file_path = latest.get(file_key)
            if not file_path:
                continue

            fp = Path(file_path)

            if not fp.exists():
                continue  # Missing files caught by validate_catalog

            file_size = fp.stat().st_size

            if file_size == 0:
                flags.append(f"empty_file:{lang_label}")
                report["empty_files"] += 1
                report["issues"].append(
                    {
                        "form_id": form_id,
                        "check": "empty_file",
                        "file": file_path,
                        "detail": f"{lang_label} file is 0 bytes",
                    }
                )
                logger.warning("Empty file: %s (%s) — form_id=%s", file_path, lang_label, form_id)
                continue

            if file_size < MIN_VALID_PDF_SIZE:
                flags.append(f"tiny_file:{lang_label}")
                report["issues"].append(
                    {
                        "form_id": form_id,
                        "check": "tiny_file",
                        "file": file_path,
                        "size": file_size,
                        "detail": f"{lang_label} file is {file_size} bytes (under {MIN_VALID_PDF_SIZE}B threshold)",
                    }
                )

            # ── File type detection (magic bytes) ──────────────────────────
            actual_type = _detect_file_type(file_path)

            if actual_type and actual_type != "pdf":
                flags.append(f"mislabeled:{lang_label}:{actual_type}")
                report["mislabeled_files"] += 1
                report["issues"].append(
                    {
                        "form_id": form_id,
                        "check": "mislabeled_file",
                        "file": file_path,
                        "expected": "pdf",
                        "actual": actual_type,
                        "detail": f"{lang_label} file is actually {actual_type.upper()}, not PDF",
                    }
                )
                logger.warning(
                    "Mislabeled file: %s is %s, not PDF — form_id=%s",
                    file_path,
                    actual_type.upper(),
                    form_id,
                )

            # ── PDF integrity check ────────────────────────────────────────
            if actual_type == "pdf":
                try:
                    content = fp.read_bytes()
                    tail = content[-32:]
                    if b"%%EOF" not in tail:
                        flags.append(f"truncated_pdf:{lang_label}")
                        report["corrupt_files"] += 1
                        report["issues"].append(
                            {
                                "form_id": form_id,
                                "check": "truncated_pdf",
                                "file": file_path,
                                "detail": f"{lang_label} PDF missing %%EOF marker — possibly truncated",
                            }
                        )
                        logger.warning(
                            "Truncated PDF: %s missing %%EOF — form_id=%s",
                            file_path,
                            form_id,
                        )
                except OSError as exc:
                    flags.append(f"unreadable:{lang_label}")
                    report["corrupt_files"] += 1
                    report["issues"].append(
                        {
                            "form_id": form_id,
                            "check": "unreadable_file",
                            "file": file_path,
                            "detail": f"{lang_label} file could not be read: {exc}",
                        }
                    )

        if not flags:
            del entry["preprocessing_flags"]

    # ══════════════════════════════════════════════════════════════════════════
    # Pass 2: Cross-entry checks (duplicate content detection)
    # ══════════════════════════════════════════════════════════════════════════

    hash_to_forms: dict[str, list[str]] = {}
    for entry in catalog:
        h = entry.get("content_hash")
        fid = entry.get("form_id")
        if h and fid:
            hash_to_forms.setdefault(h, []).append(fid)

    for content_hash, form_ids in hash_to_forms.items():
        if len(form_ids) > 1:
            report["duplicate_hashes"] += 1
            report["issues"].append(
                {
                    "check": "duplicate_content",
                    "content_hash": content_hash,
                    "form_ids": form_ids,
                    "detail": f"{len(form_ids)} forms have identical content (hash: {content_hash[:16]}...)",
                }
            )
            logger.warning(
                "Duplicate content detected: hash %s... shared by form_ids %s",
                content_hash[:16],
                form_ids,
            )

    logger.info(
        "Preprocessing complete: %d forms processed, "
        "%d names normalized, %d slugs normalized, "
        "%d mislabeled files, %d empty files, "
        "%d corrupt files, %d duplicate hashes",
        report["total_processed"],
        report["names_normalized"],
        report["slugs_normalized"],
        report["mislabeled_files"],
        report["empty_files"],
        report["corrupt_files"],
        report["duplicate_hashes"],
    )

    return report
