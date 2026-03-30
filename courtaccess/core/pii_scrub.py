"""
courtaccess/core/pii_scrub.py

PII detection for uploaded documents and OCR-extracted text.
Uses Microsoft Presidio with custom recognizers for Massachusetts court patterns.

STUB/REAL HYBRID:
  - Presidio is always active (it's a fast CPU library, no GPU needed).
  - Custom MA-specific recognizers are added on top of built-in detectors.
  - Findings are LOGGED only — PII is never auto-redacted per court policy.

PRODUCTION NOTES:
  - Add more custom patterns as QA reveals missed MA-specific PII.
  - Do NOT change the output contract — downstream audit_logs depend on it.

OUTPUT CONTRACT:
  {
      "findings": [
          {
              "entity_type": str,    # e.g. "PERSON", "MA_DOCKET_NUMBER"
              "start":       int,    # char offset in text
              "end":         int,
              "score":       float,  # 0.0-1.0 confidence
              "text_excerpt": str,   # redacted snippet for logging
          }
      ],
      "finding_count": int,
      "has_pii":       bool,
  }
"""

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ── Lazy-load Presidio to avoid import cost at module load ────────────────────
_analyzer = None


def _get_analyzer():
    """
    Build and cache the AnalyzerEngine with MA-court custom recognizers.
    Lazy-loaded so tests that mock pii_scrub don't incur the spaCy/Presidio
    startup cost.
    """
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry

    registry = RecognizerRegistry()
    registry.load_predefined_recognizers()

    # ── Custom MA court recognizers ───────────────────────────────────────────

    # MA docket number: e.g. 2301CR00456, 23-CR-00456, 23CR0045
    docket_pattern = PatternRecognizer(
        supported_entity="MA_DOCKET_NUMBER",
        patterns=[
            Pattern(
                name="ma_docket",
                regex=r"\b\d{2,4}[-\s]?[A-Z]{1,2}[-\s]?\d{4,6}\b",
                score=0.85,
            )
        ],
        context=["docket", "case", "matter", "no.", "number"],
    )

    # MA court file number: e.g. SJC-12345, SUCV2022-01234
    court_file_pattern = PatternRecognizer(
        supported_entity="MA_COURT_FILE_NUMBER",
        patterns=[
            Pattern(
                name="ma_court_file",
                regex=r"\b[A-Z]{2,6}[-_]?\d{4,6}[-_]?\d{0,5}\b",
                score=0.7,
            )
        ],
        context=["file", "case", "court", "docket"],
    )

    registry.add_recognizer(docket_pattern)
    registry.add_recognizer(court_file_pattern)

    _analyzer = AnalyzerEngine(registry=registry)
    logger.info("Presidio AnalyzerEngine initialized with MA court custom recognizers.")
    return _analyzer


def scrub_pii(text: str, language: str = "en") -> dict:
    """
    Scan text for PII using Presidio.
    Findings are logged for audit compliance — text is NOT modified.

    Args:
        text:     The text to scan (OCR-extracted or uploaded document body).
        language: ISO language code for Presidio NLP engine (default: "en").

    Returns:
        Dict matching OUTPUT CONTRACT above.
    """
    if not text or not text.strip():
        return {"findings": [], "finding_count": 0, "has_pii": False}

    analyzer = _get_analyzer()
    results = analyzer.analyze(text=text, language=language)

    findings = []
    for r in results:
        # Redact the actual text in the log excerpt (show entity type only)
        excerpt = f"[{r.entity_type}]"
        findings.append(
            {
                "entity_type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "score": round(r.score, 3),
                "text_excerpt": excerpt,
            }
        )

    has_pii = len(findings) > 0
    if has_pii:
        logger.warning(
            "PII detected: %d finding(s) — types: %s. Findings logged, text not modified.",
            len(findings),
            list({f["entity_type"] for f in findings}),
        )
    else:
        logger.info("PII scan complete: no findings.")

    return {
        "findings": findings,
        "finding_count": len(findings),
        "has_pii": has_pii,
    }
