# CourtAccess AI — Full Test Suite Summary

**Last updated:** 2026-04-08
**Total passing tests:** ~2,245+

---

## Master Index

| Area | Test Files | Approx. Tests |
|------|-----------|---------------|
| [Core](#core) | 16 files | ~632 |
| [Languages & Forms](#languages--forms) | 5 files | ~199 |
| [Speech](#speech) | 6 files | ~255 |
| [API](#api) | 10 files | ~333 |
| [Monitoring](#monitoring) | 2 files | 112 |
| [DB](#db) | 5 files | 163 |
| **Total** | **44 files** | **~1,694+** |

> Tests in Core / Languages / Forms / Speech / API were written in an earlier session and are documented as supplied. Tests in **Monitoring** and **DB** were written in this session and are documented in full detail.

---

---

# Core

## `test_validation.py` — 73 tests
**File tested:** `courtaccess/core/validation.py`

- `_detect_file_type` — classifies files as PDF/HTML/unknown by magic bytes and size thresholds
- `_normalize_form_name` — strips punctuation, collapses whitespace from form names
- `_normalize_slug` — cleans slugs to lowercase alphanumeric-with-hyphens
- `run_preprocessing` Pass 1 — per-entry validation: missing fields, bad file types, PDF anomalies, slug/name normalization, flags
- `run_preprocessing` Pass 2 — cross-entry: duplicate hash detection, form-level counting

**Why:** The validation pipeline is the first stage every document passes through before ingestion. Bugs here silently corrupt the catalog. Tests pin every flag, every edge case (truncated PDFs, HTML files disguised as PDFs, boundary file sizes, slug collisions).

---

## `test_classify_document.py` — 26 tests
**File tested:** `courtaccess/core/classify_document.py`

- `_stub_classify` — always returns legal, confidence 1.0, pages_reviewed=0
- `classify_document` routing — when to use stub vs real (flags, missing project ID, no auth)
- `_real_classify` output contract — all required keys, correct pages_reviewed
- Fail-closed guards — malformed JSON, missing classification/confidence keys, empty response → `ClassificationError`
- `ClassificationError` vs `RuntimeError` distinction — bad AI response ≠ network failure
- Markdown fence stripping — Vertex wraps JSON in ` ```json ``` `, must be stripped before parse

**Why:** This is the security gate. A bug that lets non-legal documents through would corrupt the entire pipeline. `ClassificationError` vs `RuntimeError` must stay distinct because callers handle them differently (retry vs skip).

---

## `test_pdf_utils.py` — 139 tests
**File tested:** `courtaccess/core/pdf_utils.py`

- `get_font_code`, `get_font_size`, `fit_fontsize` — font lookups and size fitting
- `safe_color`, `color_to_hex` — color validation and conversion
- `_is_blank_fill_line` — underscore/dash fill detection
- `_should_never_translate`, `_is_form_field_line` — translation skip logic
- `_classify` — line classification (HEADER / BODY / SKIP / etc.)
- `_lines_are_same_row`, `_group_lines_into_rows` — layout grouping
- `_detect_alignment`, `_union_rects`, `_split_line_by_columns` — geometry
- `_find_tightest_cell`, `_get_available_width` — cell/column fitting
- 3 skipped (need real pymupdf page): `get_background_color`, `_get_cell_rects`, `_get_block_units`

**Why:** `pdf_utils.py` is the largest utility file in the pipeline — 30+ pure functions. These are the building blocks for every PDF reconstruction. A wrong `_classify` call produces wrong translations; a wrong `_union_rects` produces misaligned output.

---

## `test_ingest_document.py` — 37 tests
**File tested:** `courtaccess/core/ingest_document.py`

- `is_content_image` — DIGITAL pages always False; SCANNED with 95%+ coverage and no content → True
- `classify_page` — BLANK / SCANNED / DIGITAL classification using mocked pymupdf pages
- Image coverage calculation — primary path (`get_image_rects`), fallback-1 (image block bboxes), fallback-2 (large image assumption)
- Coverage boundary at 40% (strict greater-than)
- `ingest_pdf` — `FileNotFoundError` / `ValueError` guards, output contract, page numbering, PNG output, custom output dir, DIGITAL classification of real PDFs

**Why:** Page classification drives the entire pipeline branch (DIGITAL → vector extraction, SCANNED → OCR, BLANK → skip). A wrong classification routes a document to the wrong processor entirely.

---

## `test_logger.py` — 15 tests
**File tested:** `courtaccess/core/logger.py`

- Return type, name matching, registry identity (same name → same object)
- Handler added, is `StreamHandler`, streams to stdout
- Idempotency — calling twice on same name does NOT add duplicate handlers
- Log level is INFO, propagation is disabled
- Formatter includes `%(levelname)s`, `%(name)s`, `%(message)s`, and ISO-8601 datefmt

**Why:** Wrong propagation = duplicate log lines in production. Duplicate handlers = doubled output. Wrong datefmt = broken Cloud Logging timestamp parsing. These are silent bugs that only show up in production.

---

## `test_config.py` — 15 tests
**File tested:** `courtaccess/core/config.py`

- `database_url` computed field — assembles `postgresql+asyncpg://user:pass@host:port/db` correctly
- Field type validation — `debug` is bool, `postgres_port` is int, `use_real_*` flags are bool, thresholds are float
- Optional fields accept None
- `get_settings()` returns the module-level singleton (same object, not a factory)

**Why:** A wrong `database_url` means the app connects to the wrong database. `get_settings()` being a factory instead of a singleton would cause divergent config state across request handlers.

---

## `test_translation.py` — 73 tests
**File tested:** `courtaccess/core/translation.py`

- `_is_blank_fill_line` — blank fill detection
- `_extract_citations` — G.L. c., § symbols, URLs, court codes → `RFCT{n}RF` placeholders
- `_restore_placeholders` — placeholder → original, handles space-corrupted NLLB tokens
- `_is_preserve_only` — RFCT/RFPN-only text needs no translation; RFCN NOT stripped
- Stub mode lifecycle — `load()` skips models, returns self
- `translate_text()` output contract — original, translated, confidence
- Step 0 (blank fill) and Step 0.5 (form tokens) protection — both bypass NLLB entirely
- `batch_translate()` — same length, same order
- `_extract_court_names()` — `RFCN{n}RF` placeholder → target language translation
- `_apply_court_name_safety_net()` — case-insensitive post-translation replacement
- `unload()` — clears all model references, safe to call twice
- `_ensure_loaded()` — no-op in stub mode; `RuntimeError` in real mode with unloaded models

**Why:** The protection pipeline is the most complex logic in the system. Each step prevents a class of mistranslation (citations corrupted, court names anglicized, proper nouns mangled). The hallucination ratio guard prevents garbage output from reaching documents.

---

## `test_legal_review.py` — 59 tests
**File tested:** `courtaccess/core/legal_review.py`

- Constructor — env var parsing (`VERTEX_MAX_RETRIES` bad values, min=1), flag routing
- `_cache_key` — deterministic SHA-256, order matters, whitespace stripped
- `_redis_key` — namespace format `ca:tlcache:{version}:{lang}:{sha}`
- `_build_glossary_snippet` — matches terms case-insensitively, max 15, empty glossary returns `""`
- `_strip_fences` — removes ` ```json ``` ` and ` ``` ` from LLM output
- `_validate_results` — hallucination guard: ratio < 0.2 or > 5.0 → keeps original translation
- `review_legal_terms` — stub mode returns `{status: "ok", corrections: []}`
- `verify_batch` — stub passthrough; empty input returns unchanged
- `_build_verification_prompt` — contains language label, all pairs, glossary section, JSON array instruction
- `_get_redis` — no URL → None; unavailable flag → None; connection failure → sets unavailable flag
- `_call_llama_cached` — cache hit skips Vertex; cache miss calls Vertex; Redis error disables cache

**Why:** The LLM verification layer is the final quality gate before documents are returned to users. Cache correctness matters for cost. The hallucination guard prevents a 10× longer or 10× shorter AI output from replacing a correct translation.

---

## `test_gcs.py` — 39 tests
**File tested:** `courtaccess/core/gcs.py`

- `_get_storage_client` — lru_cache bypass via patch, singleton behaviour, import error propagation
- `upload_file` — correct bucket/blob addressed, `upload_from_filename` called with right path
- `download_file` — parent directories created, `download_to_filename` called, `FileNotFoundError` on missing blob, NotFound and Forbidden GCS exceptions mapped to Python stdlib errors, error message contains bucket + blob name
- `delete_blob` — `delete()` called, NotFound swallowed (idempotent), other exceptions re-raised, correct bucket/blob addressed
- `blob_exists` — returns True/False based on mock `.exists()` result
- `get_blob_size` — `reload()` called before reading `.size`, returns None on NotFound and generic exceptions

**Why:** Every file in the translation pipeline passes through GCS. Wrong error mapping (e.g. swallowing Forbidden silently) would lose audit evidence of auth failures.

---

## `test_reconstruct_pdf.py` — 37 tests
**File tested:** `courtaccess/core/reconstruct_pdf.py`

- `_citation_fallback` — pure string restoration from RFCT placeholder map
- `_restore_caps` — ALL_CAPS restoration when `is_caps=True`, passthrough otherwise
- `_insert_unit_html` — inserts HTML into a mocked pymupdf page, calls `insert_htmlbox` with correct rect
- `reconstruct_pdf` — end-to-end on real minimal PDFs: `FileNotFoundError` for missing input, `ValueError` for non-PDF bytes, output file created, preserved regions inserted unchanged, translated regions inserted with translated text

**Why:** `reconstruct_pdf` is the final stage that writes the translated document. A wrong rect or wrong text insertion would corrupt every output PDF silently.

---

## `test_docx_translation.py` — 37 tests
**File tested:** `courtaccess/core/docx_translation.py`

- `_split_fill_suffix` — underscore/dash fill suffix split, trailing space preserved in fill portion, no suffix returns empty fill
- `translate_docx` — real `.docx` files created via python-docx; fill suffixes stripped before translation and reattached after; translator called with clean text only; reviewer called on all spans; table cells translated; different fill characters handled

**Why:** Docx translation is the most structurally complex output format. The fill-suffix reattachment prevents translated forms from losing blank lines (e.g. `Signature: ______`) which would make them unusable.

---

## `test_ocr_handwritten.py` — 13 tests
**File tested:** `courtaccess/core/ocr_handwritten.py`

- `_USE_REAL` flag — evaluated at import from `USE_REAL_HANDWRITING_OCR` env var; patched per-test via `patch.object`
- `extract_handwritten_text` routing — stub mode always calls `_stub_extract`; real mode calls `_real_extract`
- `_stub_extract` — always returns `[]` regardless of input
- `_real_extract` exception handling — Google Vision API error returns `[]` and logs a warning, doesn't propagate

**Why:** Handwritten OCR is the slowest and most expensive path. The routing logic being wrong would make the test suite depend on Google Vision credentials.

---

## `test_sensitivity_analysis.py` — 59 tests
**File tested:** `courtaccess/core/sensitivity_analysis.py`

- `_stdev` — population std-dev: empty/single → 0.0, identical values → 0.0, classic `[2,4,4,4,5,5,7,9]` → 2.0, return type
- `_pearson` — Pearson r: n<2 → None, mismatched lengths → None, zero variance → None, perfect correlation → ±1.0, result bounded in [-1, 1]
- `_load_catalog` — missing file → `[]`, valid JSON round-trip, malformed JSON → `JSONDecodeError`
- `run_threshold_sweep` — grid size = 9×7 = 63 cells, required keys per entry, `run_bias_detection` called once per cell with correct kwargs, CRITICAL flag counting is case-insensitive, MLflow=None no crash, MLflow `log_params` called per cell, MLflow error suppressed
- `run_input_characteristics` — no `DATABASE_URL` → None, DB connection failure → None, empty rows → `row_count=0`, rows → avg confidence and correction rate computed correctly
- `run_sensitivity_analysis` — returns `{threshold_sweep, input_characteristics}`, mlflow import failure → graceful, `catalog_path=None` uses default
- Module constants: sweep range sizes, values, experiment name type

**Why:** The sensitivity analysis runs at deploy time and writes to MLflow. Bugs in `_stdev` or `_pearson` produce wrong threshold sensitivity scores that could mask model regressions.

---

## `test_ocr_printed.py` — 34 tests
**File tested:** `courtaccess/core/ocr_printed.py`

- `_scanned_region` — all 14 contract fields present, bbox == avail_bbox for scanned pages, confidence/page_num/font_size stored correctly, defaults: helv font, black RGB, not bold/centered/preserved
- `OCREngine.__init__` — `_use_real` from `USE_REAL_OCR` env var, `OCR_CONFIDENCE_THRESHOLD` read as float
- `load()` — returns self for chaining, stub mode leaves paddle/tesseract unloaded, paddle import failure leaves `_paddle=None`, tesseract import failure leaves `_tesseract_available=False`
- `extract_text_from_pdf` — `FileNotFoundError` for missing path, output keys `regions` and `full_text`, `full_text = "\n".join(region["text"])`, real PDF with text → non-empty regions, empty PDF → `[]`, multi-page → `page` field matches page index
- `_extract_scanned_paddle` — None result → `[]`, empty result → `[]`, confidence below threshold filtered, text `"X"` filtered, blank fill lines filtered, valid high-confidence result returned with correct contract fields
- `_extract_scanned_tesseract` — pytesseract/PIL `ImportError` → `[]`

**Why:** Page routing is the most important branching logic in the OCR pipeline. A wrong confidence threshold check would let low-quality OCR text into the reconstruction phase.

---

## `test_register_models.py` — 22 tests
**File tested:** `courtaccess/core/register_models.py`

- `_parse_dvc_file` — missing file → None, md5/size/path extracted from YAML-style content, each field falls back correctly when absent
- `register_models` — returns list of length `len(DVC_MODELS) + 1` (6 DVC + llama), llama entry always last, missing DVC files get `registered=False`, reason="dvc_file_missing", MLflow unavailable → all reason="mlflow_unavailable", valid DVC file → correct md5/size_mb, mock MLflow → `registered=True`, `start_run` called per found model, MLflow error inside run → `registered=False`, `gcs_remote` reads from `GCS_BUCKET_MODELS` env

**Why:** A wrong `size_mb` calculation or missing llama entry would corrupt the model registry, making it impossible to trace which weights are deployed.

---

## `test_validate_models.py` — 33 tests
**File tested:** `courtaccess/core/validate_models.py`

- `_run_name` — contains "stub"/"real" based on flag, starts with "validation-", contains today's date
- `VALIDATION_SET` — exactly 20 entries, all 2-tuples of non-empty strings, first entry is arraignment, English phrases unique
- `validate()` output contract — params, metrics, threshold keys; all 5 metric keys present
- Metric computation — `nllb_non_empty_rate=1.0` when all translated, `nllb_changed_rate=1.0` when output ≠ input, `nllb_avg_confidence` averaged from mock confidence values, `llama_correction_rate=0.0` when reviewer passes through
- Edge cases — `nllb_non_empty_rate=0.0` when all empty, `llama_correction_rate=1.0` when reviewer changes all, `not_verified_rate=1.0` when all prefixed with `[NOT VERIFIED]`, `nllb_changed_rate=0.0` when translator echoes input
- Translator called once per phrase (20 calls); reviewer called once with all 20 phrases
- Settings reflected in params (`use_real_translation`, `nllb_model_path`, `threshold`)

**Why:** This is the CI/CD quality gate — a wrong rate calculation could let a broken model pass or block a good one. The 20-phrase fixed reference set is tested as a constant so accidental edits are immediately caught.

---

---

# Languages & Forms

## `test_base.py` — 23 tests
**File tested:** `courtaccess/languages/base.py`

- Field defaults — `court_name_translations`, `legal_overrides`, `form_token_translations` default to `{}`, `glossary_skip_lines` to `set()`, `ready_for_production` to `True`
- `__post_init__` logic — `llama_lang_label` falls back to `display_name` when not explicitly set, but preserves an explicit value
- Field types — all required fields store the correct types
- Mutable default isolation — mutating one instance's dict/set does not affect a second instance; catches the classic Python dataclass shared-mutable-default footgun

**Why:** A broken default (e.g. a shared dict across instances) would cause one language's overrides to bleed into another at runtime — a silent data corruption bug that only surfaces when two languages are used in the same process.

---

## `test_spanish.py` — 38 tests
**File tested:** `courtaccess/languages/spanish.py`

- Identity — code, `display_name` (both "Spanish" and "Español"), `llama_lang_label`, `ready_for_production`
- NLLB codes — source `eng_Latn`, target `spa_Latn`
- Court name translations — all 8 Massachusetts courts present, exact value check for Massachusetts Trial Court, no empty values
- Legal overrides — 10+ specific term checks (defendant → acusado, commonwealth → Commonwealth, etc.), all keys lowercase, all values strings
- Form token translations — 6 specific token checks (DATE → FECHA, SIGN → FIRMAR, etc.), all keys uppercase
- Glossary skip lines — legal, revised, introduction present, all lowercase, stored as set
- Structural rules — override keys lowercase, token keys uppercase, no empty translation values

**Why:** Spanish is the primary language for CourtAccess AI. Every mistranslation of a court name or legal term in this config propagates to every document processed. Pinning exact values means a typo or accidental revert is caught immediately.

---

## `test_portuguese.py` — 39 tests
**File tested:** `courtaccess/languages/portuguese.py`

- Same structural coverage as Spanish — identity, NLLB codes (`por_Latn`), all 8 courts, legal overrides, form tokens, skip lines
- Specific Portuguese values — defendant → réu, verdict → veredito, DATE → DATA, SIGN → ASSINAR, Massachusetts Trial Court → Tribunal de Julgamento de Massachusetts
- Cross-language diff tests — explicitly asserts Portuguese values differ from Spanish equivalents: `nllb_target`, defendant, DATE, SIGN

**Why:** Portuguese config was written after Spanish and shares the same structure, making it a copy-paste error risk. The cross-language diff tests exist specifically to catch cases where a Portuguese value was accidentally left as its Spanish equivalent.

---

## `test_parse_glossary.py` — 29 tests
**File tested:** `courtaccess/forms/parse_glossary.py`

- `load()` — success path, returns self, populates glossary dict, raises `FileNotFoundError` with a helpful message when JSON is missing
- `get_matching_terms()` — case-insensitive matching, respects `max_terms` (default 8), longer terms win over shorter overlapping ones, empty text and empty glossary both return `{}`, returns correct translations not just correct keys
- `_should_skip()` — y-coordinate boundaries (strict: y<55 and y>725 skip, y==55 and y==725 do not), empty/whitespace/single-letter/two-letter-alpha text skipped, two-digit strings not skipped (tests the `isalpha()` branch), known header lines skipped case-insensitively
- `parse_pdf()` — raises on missing PDF, merges `legal_overrides` on top of parsed terms, saves JSON to disk
- Integration — loads the actual committed `glossary_es.json` and `glossary_pt.json` and confirms they are non-empty and parseable

**Why:** The glossary drives the contextual translation hints injected into every LLM prompt. A broken `get_matching_terms()` silently omits hints, degrading translation quality.

---

## `test_scraper.py` — 70 tests
**File tested:** `courtaccess/forms/scraper.py`

- `_now()` — returns a valid ISO-8601 UTC timestamp with timezone info
- `_sha256()` — correct hash against known value, stable across calls, distinct for different inputs, handles empty bytes
- `_slug_from_url()` — strips `/download` suffix, handles trailing slashes, preserves hyphens
- `_is_docx()` — real DOCX bytes (valid ZIP with word/document.xml) pass; plain ZIPs, PDF magic bytes, empty bytes, and random bytes all fail
- `_find_by_url()` / `_find_by_hash()` — found/not-found/empty catalog cases, returns first match on duplicates
- `_merge_appearances()` — adds new divisions, skips duplicates by division name, handles empty input, correctly deduplicates within a single call
- Scenario handlers A–E — `_handle_deleted_form` sets `status=archived`; `_handle_renamed_form` updates name, slug, and source URL; `_handle_no_change` updates only `last_scraped_at`; `_handle_new_form` adds entry to catalog with correct fields, enqueues form ID; `_handle_updated_form` increments version, inserts new version at front, sets `needs_human_review=True`
- Filesystem helpers — `_version_dir` creates directory at correct path and is idempotent; `_save_original` writes correct bytes at correct path; `_save_translation` writes `_es.pdf` and `_pt.pdf` suffixes correctly

**Why:** The five scenario handlers are the core state machine. A bug in `_handle_updated_form` that fails to insert the new version at the front would corrupt version history for every subsequently updated form.

---

---

# Speech

## `test_vad.py` — 43 tests
**File tested:** `courtaccess/speech/vad.py`

- `SpeechSegmentDetector.__init__` — `silence_chunks_threshold` correctly derived from `(silence_threshold_ms / chunk_duration_ms)`, default state fields are all zero/None/False, custom sample rates calculate correctly
- `update()` state machine — `speech_start` event fires on first speech chunk; continuing speech returns `type=None`; silence before speaking is a no-op; `silent_chunks` increments only while speaking; `speech_end` fires exactly when the silence chunk count reaches the threshold (not before); `speech_end` carries a float `duration` field; `is_speaking` and `silent_chunks` reset after end; brief silence below threshold does not end the utterance; speech resuming after brief silence resets `silent_chunks`; full start→end→start cycle fires correct event sequence
- `reset()` — clears all four state fields; a new cycle after reset fires `speech_start` correctly
- VADService singleton — two instantiations with a mocked `_load_model` return the same instance

**Why:** A wrong `silence_chunks_threshold` calculation makes the system either cut off speakers mid-sentence or hold open utterances indefinitely.

---

## `test_turn_taking.py` — 67 tests
**File tested:** `courtaccess/speech/turn_taking.py`

- `FloorState` enum — all five string values (idle, a_speaking, a_processing, b_speaking, b_processing)
- `TurnStateMachine.__init__` — initial state is IDLE, floor holder is None, no locks active
- `try_speech_start()` — role A and B can each claim an idle floor; A cannot speak when B holds the floor and vice versa; the same role can re-claim its own floor; a locked user is rejected regardless of floor availability
- `holds_floor()` — true for the active speaker, false for the other role, false when idle
- `on_speech_end()` — returns True for the floor holder, False for any other role; transitions to `_PROCESSING` state; sets `_grace_expiry` approximately `grace_ms` seconds into the future
- `release_floor()` — resets to IDLE and clears floor holder; no-op when the caller doesn't hold the floor
- `lock_user()` / `is_locked()` — locking a non-speaker makes `is_locked()` return True; queued TTS locks extend rather than shorten existing locks (max semantics); expired locks return False
- `_check_grace()` — a backdated `_grace_expiry` releases the floor to IDLE; a future expiry leaves the floor holder unchanged
- `get_status()` — correct state, floor_holder, grace_ms, lock booleans, non-negative `lock_remaining_ms`
- `__repr__` — contains state=, floor=, and A_locked(...) when locked

**Why:** A wrong rejection in `try_speech_start` means one participant's audio is silently dropped. Missing the max semantics in `lock_user` means a second TTS segment can shorten the echo-suppression window.

---

## `test_session_recorder.py` — 75 tests
**File tested:** `courtaccess/speech/session_recorder.py`

- `_resample_if_needed()` — passthrough when source rate matches target; 48 kHz→16 kHz yields exactly n × (16000/48000) samples; 8 kHz→16 kHz upsamples correctly; empty array returns empty; output is always float32
- `_float32_to_int16_bytes()` — zero maps to null bytes; +1.0 maps to 32767; -1.0 maps to -32767; values above 1.0 are clipped to 32767; values below -1.0 are clipped to -32767; output length is always n_samples × 2 bytes
- `add_speech_pcm()` — appends to the speaker's track; pads the other track with silence of equal byte length; updates `_sample_counts` for both roles; resamples 48 kHz input to 1600 samples at 16 kHz
- `add_tts_pcm()` — parses a valid WAV and appends to the target track; pads the other track; empty bytes is a no-op; invalid WAV bytes don't raise
- `finalize()` — creates WAV files for both tracks; filenames follow `{session_name}_{role}_{lang}.wav` convention; written WAV is valid; works even with empty tracks
- `TranscriptLogger.add_entry()` — `turn_index` auto-increments; all fields stored correctly; optional fields default to None/False
- `TranscriptLogger.format_text()` — header contains SESSION TRANSCRIPT and session name; entry text and translation appear; zero-entry log renders without crashing; ASR confidence and verified flag appear when set
- `TranscriptLogger.serialize()` — returns a dict with all session metadata; `duration_seconds` computed correctly; `spoken_at` is converted to ISO-8601 string; result is directly JSON-serializable
- `TranscriptLogger.finalize()` — writes a `.txt` file named `{session_name}_transcript.txt`
- `_sha256_file()` — matches hashlib.sha256 for known data; different contents produce different digests
- `write_manifest()` — creates a JSON file; includes SHA-256 hash and size for every artifact; participants metadata is correct

**Why:** Wrong silence padding lengths in `add_speech_pcm` means the two language tracks fall out of sync. The `serialize()` ISO-8601 test is critical because the output goes directly to GCS as a JSON transcript; a non-serializable datetime object would crash the upload silently.

---

## `test_legal_verifier.py` — 26 tests
**File tested:** `courtaccess/speech/legal_verifier.py`

- `LANG_LABELS` — all three short codes (en, es, pt) map to the correct full-language strings
- `VerificationResult` dataclass — all five fields stored and typed correctly
- `LegalVerifierService._fallback()` — returns the raw translation unchanged; `used_fallback=True`; `accuracy_score=1.0`; note contains "unavailable" or "machine translation"; handles empty string input
- `LegalVerifierService._parse_response()` — valid JSON parsed into all three fields; markdown fences stripped before parse; missing `verified_translation` falls back to raw; missing `accuracy_score` defaults to 1.0; score clamped to [0.0, 1.0] on both sides; score rounded to 3 decimal places; empty/whitespace-only `verified_translation` falls back to raw; invalid JSON returns a fallback result
- `get_legal_verifier()` — returns None when `use_vertex_legal_review=False`; returns None when `vertex_project_id` is empty even if the flag is True

**Why:** Score clamping matters because an LLM occasionally returns 1.1 or -0.05. The whitespace-only test covers a real LLM failure mode where the model outputs `" "` — without the strip-and-fallback, empty audio would be sent to the user.

---

## `test_mt_service.py` — 22 tests
**File tested:** `courtaccess/speech/mt_service.py`

- `LANG_CODE_TO_NLLB` — all three short codes map to correct Flores-200 BCP-47 strings (`eng_Latn`, `spa_Latn`, `por_Latn`)
- `NLLB_TO_LANG_CODE` — exact inverse of `LANG_CODE_TO_NLLB` for all entries
- `SUPPORTED_LANGUAGES` — contains en, es, pt; is a set; matches `LANG_CODE_TO_NLLB` keys exactly
- `MTService.translate()` early-return paths — empty string returns `""`; whitespace-only returns `""`; same source and target language returns the original text unchanged; unsupported source language returns original; unsupported target language returns original
- `MTService.translate()` with mocked translator — tokenizer encode and translator `translate_batch` are called; special tokens (`</s>`, `spa_Latn`) are stripped before passing to decode
- MTService singleton — two instantiations with mocked `_load_model` return the same object

**Why:** A wrong language code mapping would translate every Portuguese utterance into Spanish and vice versa — a critical and silent error. The early-return tests run without any model loaded; a missing `if not text` guard would crash the inference pipeline with an empty input.

---

## `test_tts.py` — 22 tests
**File tested:** `courtaccess/speech/tts.py`

- `VOICE_MAP` — contains entries for en, es, pt; each entry has a `name` key; English name contains `en_US`, Spanish `es_ES`, Portuguese `pt_BR`
- `SUPPORTED_LANGUAGES` — is a set; contains all three codes; matches `VOICE_MAP` keys exactly
- `_resolve_voice_path()` error paths — raises `RuntimeError` mentioning `PIPER_TTS_EN_PATH` when env var is unset; raises when the configured directory doesn't exist; raises "No .onnx" when the directory exists but contains no `.onnx` files; resolves the exact expected voice name when the file is present; falls back to glob and picks any `.onnx` when the exact name isn't found
- `TTSService.synthesize()` early returns — empty string returns `b""`; whitespace-only returns `b""`; unsupported language returns `b""`
- `TTSService.synthesize()` with mocked voice — `synthesize_wav` is called on the loaded voice; result is non-empty bytes
- TTSService singleton — two instantiations with mocked `_load_voices` return the same instance

**Why:** The three error paths in `_resolve_voice_path` each represent a different deployment failure mode. The `synthesize()` empty-input tests matter because VAD sometimes fires on noise bursts that Whisper transcribes as empty strings.

---

---

# API

## `test_health.py` — 6 tests
**File tested:** `api/main.py` (health and root endpoints)

- `GET /health` — returns 200, `status == "ok"`, `version == "0.1.0"`, `environment == "test"`
- `GET /` — returns 200, response body contains "CourtAccess" in the `name` field

**Why:** The health endpoint is polled by GCP load balancer. If it returns a wrong status string or fails to mount, deployments are blocked silently.

---

## `test_auth.py` — 38 tests
**File tested:** `api/auth.py`

- `hash_email()` — 8-char hex digest, deterministic, distinct for different inputs
- `verify_firebase_token()` — success path, `ExpiredIdTokenError`/`RevokedIdTokenError`/`InvalidIdTokenError`/`UserDisabledError`/generic exception all map to 401; `WWW-Authenticate: Bearer` header present on rejection
- `create_room_token()` / `verify_room_token()` — round-trip preserves `session_id` and `rt_request_id`; expired tokens raise 401; tampered signature raises 401; wrong secret raises 401; wrong type claim raises 401; wrong sub claim raises 401; `exp` claim is ~4 hours from now
- `get_or_create_user()` — existing user: updates `last_login_at` to a recent timestamp, updates `email_verified`, commits and refreshes; empty/whitespace email raises 401; Firebase UID backfill sets `auth_provider`; new user: all required fields populated, name defaults to email prefix when `display_name` absent, commits and refreshes; SAML provider auto-promotes to `court_official` (role_id=2); google.com provider stays at role_id=1
- `get_websocket_user()` — valid room JWT returns a guest `WebSocketUser` without hitting the DB; valid Firebase token returns a non-guest user; both paths reject invalid tokens with 401

**Why:** The `WWW-Authenticate` header test pins RFC 6750 compliance. The SAML auto-promotion test is critical because SAML users should never be stuck on role_id=1 after login — that would lock court staff out of their own interface.

---

## `test_dependencies.py` — 10 tests
**File tested:** `api/dependencies.py`

- `require_role()` — admin (role_id=4) passes `require_role("admin")`; public (role_id=1) is rejected with 403; court_official passes `require_role("court_official")`; interpreter is rejected by `require_role("court_official")`; `require_role("court_official", "admin")` accepts any listed role; 403 detail message names the required roles
- `require_verified_email()` — verified user passes; unverified user is rejected with 403; 403 detail message mentions email verification

**Why:** These are the reusable security gates applied across every protected route. A bug here — such as `require_role("admin")` accidentally accepting role_id=3 — would silently grant privilege escalation to every route that depends on it.

---

## `test_routes_auth.py` — 27 tests
**File tested:** `api/routes/auth.py`

- `GET /auth/me` — 200 with `user_id`, `email`, `role`, `email_verified`, `auth_provider`, `firebase_uid`, `created_at`; unverified user still gets 200 but `email_verified=False`; admin user gets `role="admin"`
- `POST /auth/select-role` public path — 200, `role="public"`, `db.add` never called, `db.commit` awaited once
- `POST /auth/select-role` non-SAML elevated role — role in response stays `"public"`; `db.add` called with a `RoleRequest` whose `status=="pending"`, `requested_role_id` matches the requested role, and `user_id` matches the caller; `db.commit` awaited
- `POST /auth/select-role` SAML auto-approval — court_official and interpreter both return the promoted role immediately; `role_approved_at` is set to a recent timestamp; `db.add` never called; invalid role returns 422; missing body returns 422; self-selecting admin never grants admin role immediately

**Why:** The `db.add.assert_not_called()` test for public and SAML paths is critical — a bug that inserts a `RoleRequest` on every role selection would flood the admin queue with false pending requests.

---

## `test_routes_documents.py` — 32 tests
**File tested:** `api/routes/documents.py`

- Bug regression — `test_known_bug_session_model_rejects_input_file_gcs_path` documents a known production bug: `Session(input_file_gcs_path=...)` raises `TypeError`. This test will fail when the route is fixed, signalling that the `_lenient_session_init` workaround should also be removed
- Upload validation — rejects unsupported content types, rejects files over 50 MB, rejects unverified email, rejects invalid target language
- PDF upload success — 201 status; response body has valid UUIDs for `session_id` and `request_id`, `status=="processing"`, `gcs_input_path` starts with `"gs://"`; exactly 2 DB rows added; `DocumentTranslationRequest` has `target_language=="spa_Latn"` and `status=="processing"`; `db.commit` awaited; Airflow triggered at a URL containing `"document_pipeline_dag"`; DAG conf contains `session_id`, `target_lang=="es"`, `nllb_target=="spa_Latn"`, `original_format=="pdf"`
- DOCX upload — 201; Airflow URL contains `"docx_pipeline_dag"`
- Airflow/GCS failures — both return 502
- Status polling — 404 when not found; DB `status=="completed"` maps to API `status=="translated"`; DB `status=="failed"` maps to API `status=="error"`; wrong user returns 403; elevated roles can view any user's documents
- List documents — 200 with empty list; invalid page/page_size return 422
- Delete document — 404 when not found; 409 when still processing; 403 for foreign user; 204 on success; exactly 2 DB rows deleted; GCS objects scheduled for deletion when present

**Why:** The status mapping test (`completed` → `translated`) is the most important correctness check — a refactor that breaks this mapping would silently return a wrong status to every polling client.

---

## `test_routes_forms.py` — 28 tests
**File tested:** `api/routes/forms.py`

- `GET /forms` — 200; correct response envelope; query params `q`, `division`, `language`, `status`, `page`, `page_size` forwarded to DB; `status` defaults to `"active"` even when not provided; invalid language code returns 422
- `GET /forms/divisions` — 200; returned list exactly matches what the DB query function returns
- `GET /forms/{form_id}` — 404 when not found; 422 for invalid UUID; 200 when found; `form_id` passed to DB query matches the path parameter exactly
- `POST /forms/{form_id}/review` — 403 for public user; 200 for admin; DB review function called with correct `form_id`, `approved`, `notes`, and non-None `reviewer_user_id`; `db.commit` awaited; 404 when form not found
- `POST /forms/trigger-scraper` — 403 for public; 200 for admin; response has `dag_run_id`; `triggered_at` parses as a valid ISO-8601 datetime within 60 seconds of now; Airflow DAG conf contains the admin's `user_id`; Airflow unreachable returns 502; Airflow HTTP error returns 502

**Why:** The `status` defaults-to-active test catches a footgun where omitting the filter returns archived forms to users. The Airflow 502 tests are essential because a silent swallow of the error would make operators believe the scrape was triggered when it was not.

---

## `test_routes_admin.py` — 44 tests
**File tested:** `api/routes/admin.py`

- Access control — all 7 admin endpoints return 403 for public users
- `GET /admin/users` — 200 for admin, empty list when DB returns none, 422 for invalid page/page_size
- `GET /admin/users/{user_id}` — 404 when not found, 200 with correct data, role name correctly mapped from `role_id`
- `POST /admin/users/{user_id}/role` — 422 for unknown role name, 404 when target user not found, `target.role_id` mutated to the correct value, `role_approved_by` set to the admin's `user_id`, `role_approved_at` set to a recent timestamp, `db.commit` awaited, `db.refresh(target)` awaited, `AuditLog` row added via `write_audit`
- `GET /admin/role-requests` — 200, empty list by default, `pending_only=false` accepted
- `POST /admin/role-requests/{id}/approve` — 404 when not found, 409 when already decided (`status ≠ pending`), `req.status` set to `"approved"`, `target.role_id` promoted to `requested_role_id`, `req.reviewed_at` timestamped, `req.reviewed_by` set to admin's `user_id`, `db.commit` awaited, `AuditLog` row written
- `POST /admin/role-requests/{id}/reject` — 404 when not found, 409 when already decided, `req.status` set to `"rejected"`, `target.role_id` NOT modified, `db.commit` awaited
- `GET /admin/audit-logs` — 200, empty list by default, 422 for invalid page/page_size

**Why:** The `role_id` NOT modified test on the reject path is the most critical assertion — a bug that applies the requested role on rejection would silently promote users who were denied.

---

## `test_routes_interpreter.py` — 26 tests
**File tested:** `api/routes/interpreter.py`

- Access control — all 3 interpreter endpoints return 403 for public users; interpreter and admin are both admitted
- `GET /interpreter/review` — 200 for interpreter and admin; `target_language=es` and `target_language=pt` filters both accepted; `target_language=zh` returns 400 with detail mentioning allowed values; response body correctly assembled from joined Session + DocumentTranslationRequest rows; invalid page returns 422
- `GET /interpreter/review/{session_id}` — 404 when not found; 200 with correct body fields including `signed_url` starts with `"https://"`
- `POST /interpreter/review/{session_id}/correct` — 404 when session not found; 201 when found; `db.commit` awaited; `db.add` called with an `AuditLog`; `AuditLog` details dict contains `original_text`, `corrected_translation`, and `target_language` from the request body; 422 when required fields are omitted

**Why:** The `AuditLog` content test is the most important assertion — the correction data must be persisted verbatim so reviewers can trace every change a human interpreter made.

---

## `test_routes_realtime.py` — 65 tests
**File tested:** `api/routes/realtime.py`

- `POST /sessions/` — 201 for court_official and admin, 403 for public; response has valid UUID `session_id`, `websocket_url` containing `"/sessions/"`, `status=="active"`
- `POST /sessions/rooms` — 201 for court_official, 403 for public, 422 when `consent_acknowledged=False`; response has `room_code`, valid `session_id` UUID, `join_url` containing the room_code; DB has `Session (type="realtime")` and `RealtimeTranslationRequest (phase="waiting")` rows added; `target_language` stored as NLLB code; room registered in in-memory `conversation_rooms`; `AuditLog` row written; `db.commit` awaited
- `POST /sessions/rooms/join` — 404 when code not found; 409 when `phase ≠ "waiting"`; 410 when code expired; 200 with room_token JWT, correct `partner_name`; `rt_request.phase` set to `"joining"`; `db.commit` awaited
- `GET /sessions/rooms/{code}/preview` — 404 for unknown code; 200 with phase and partner_name; response must NOT contain `session_id` or `creator_user_id` (PII guard)
- `GET /sessions/rooms/{code}/status` — 403 for public; 404 for unknown code; 200 for room creator; 403 for a different court_official who is not the creator; 200 for admin regardless of ownership
- `POST /sessions/rooms/{session_id}/end` — 403 for public; 404 when not found; 403 for non-creator court_official; 204 for creator; `rt_request.phase` set to `"ended"`; `session.status` set to `"completed"`; idempotent when already ended (returns 204, `db.commit` not called); `AuditLog` written; admin can end any room
- `GET /sessions/rooms` — 403 for public; 200 for court_official; created room appears in the list
- `GET /sessions/{session_id}` (in-memory) — 404 for unknown session; 200 for owner; 403 for different public user; court_official can view any user's session
- `POST /sessions/{session_id}/end` (in-memory) — 404 for unknown; 204 for owner; session status set to `"ended"`; idempotent when already ended; 403 for different user

**Why:** The preview PII guard test (`session_id` and `creator_user_id` must not appear) is critical because the preview endpoint is unauthenticated. The idempotency test on `end_room` verifies that `db.commit` is not called on a repeat end.

---

## `test_schemas.py` — 57 tests
**File tested:** `api/schemas/schemas.py`

- Enum values — `UserRole` (public, court_official, interpreter, admin), `Language` (en, es, pt), `TargetLanguage` NLLB codes, `DocumentStatus` (all 6 values), `SessionStatus`, `SessionType`
- `ROLE_ID_TO_NAME` — all 4 role IDs map correctly; unknown ID returns None
- `UserResponse.from_orm_user()` — role mapped correctly for all 4 role IDs; unknown `role_id` yields `"unknown"`; email, firebase_uid, and `created_at` preserved
- `RoleUpdateRequest` — valid roles accepted; invalid role name raises `ValidationError`; missing field raises `ValidationError`
- `UploadRequest` — defaults to both languages; notes at exactly 500 chars accepted; 501 chars raises `ValidationError`
- `RoomCreateRequest` — `consent_acknowledged=True/False` both accepted by Pydantic; `partner_name` at exactly 100 chars accepted; 101 chars raises `ValidationError`; `target_language="en"` raises `ValidationError` (English is not a valid partner language)
- `RoomJoinRequest` — 4–8 uppercase alphanumeric accepted; 3 chars raises `ValidationError`; 9 chars raises `ValidationError`; lowercase raises `ValidationError`; special characters raise `ValidationError`; `partner_name` is optional
- `TranscriptSegment` — `translation_confidence` accepts 0.0 and 1.0; 1.01 and -0.01 raise `ValidationError`; `segment_id` auto-generated as a valid UUID; `is_final` defaults to False
- `FormSearchRequest` — `q` at exactly 200 chars accepted; 201 chars raises `ValidationError`; `page_size` max 100 accepted, 101 raises `ValidationError`; page must be ≥ 1; defaults are page=1, page_size=20
- `SessionCreateRequest` — default `target_language` is `spa_Latn`, default `source_language` is `"en"`
- `WebSocketMessage` — `payload` defaults to `{}`; type field preserved
- `ErrorDetail` — code and message stored; details defaults to `{}`

**Why:** The `RoomJoinRequest` pattern test is particularly important because room codes are shared verbally in courtrooms — a schema that accepts lowercase or special characters would let guests submit malformed codes that silently fail DB lookups.

---

---

# Monitoring

> **All 112 tests are pure synchronous unit tests. No database, no filesystem (except `tmp_path` for PDF existence tests), no external services.**

## `courtaccess/monitoring/tests/test_anomaly.py` — 57 tests
**File tested:** `courtaccess/monitoring/anomaly.py`

### `TestRequiredFields` (8 tests)
Validates the `REQUIRED_FIELDS` constant contains exactly the 7 expected fields (`form_id`, `form_name`, `source_url`, `content_hash`, `status`, `version`, `last_checked`) and is a `set`.

### `TestCheckSchema` (7 tests)
Unit tests for the private `_check_schema` helper:
- Empty catalog returns `[]`
- All valid entries returns `[]`
- Entry missing one field produces one violation string containing the `form_id` and missing field name
- Entry missing multiple fields counts as one violation (one string per entry, reporting all missing fields)
- Entry with no `form_id` uses `?` as the identifier
- Multiple invalid entries each produce their own violation
- Mix of valid and invalid entries only flags the invalid one

### `TestOutputContract` (6 tests)
Verifies the return value of `run_anomaly_detection` always has `anomalies`, `anomaly_count`, and `has_critical`; that `anomaly_count == len(anomalies)`; `anomalies` is a list; `has_critical` is a bool; each anomaly dict has `check`, `severity`, and `detail`; severity values are strictly `"warning"` or `"critical"`.

### `TestFormCountDrop` (7 tests)
Check 1 — form count drop vs previous run:
- No previous metrics → check skipped entirely
- Previous `active_count=0` → skipped (avoids division by zero)
- 15% drop below 20% threshold → no flag
- Exactly 20% drop → no flag (condition is strictly `>`, not `>=`)
- 30% drop above 20% threshold → `"form_count_drop"` critical flag
- Count increase → no flag
- Detail string contains both the previous and current counts

### `TestMassNewForms` (5 tests)
Check 2 — mass new forms in one run:
- 0 new forms → no flag
- 49 new forms (< threshold 50) → no flag
- 50 new forms (= threshold) → no flag (strictly `>`)
- 51 new forms → `"mass_new_forms"` warning flag
- Detail string contains the count and threshold

### `TestDownloadFailures` (6 tests)
Check 3 — download failure rate:
- `total_attempted=0` → check skipped (avoids division by zero)
- 9% failure (< 10% threshold) → no flag
- Exactly 10% failure → no flag (strictly `>`)
- 11% failure → `"high_download_failures"` critical flag
- 100% failure rate → critical flag
- Detail string contains failed count, total, and percentage

### `TestEmptyCatalog` (4 tests)
Check 4 — empty active catalog:
- Catalog with at least one active entry → no flag
- Empty catalog list → `"empty_catalog"` critical flag
- Catalog containing only non-`"active"` entries → critical flag
- Mix of active and inactive → no flag

### `TestSchemaViolations` (3 tests)
Check 5 — schema violations:
- All valid entries → no flag
- One entry missing a field → `"schema_violations"` warning flag
- Detail string contains the count of violations

### `TestMissingPDFs` (6 tests)
Check 6 — PDF files referenced in catalog but absent on disk:
- No `file_path_original` key → check skipped for that entry
- `file_path_original=None` → check skipped
- File exists on disk → no flag (uses pytest `tmp_path`)
- File does not exist → `"missing_pdfs"` warning flag
- Detail contains the `form_id`
- Inactive (non-`"active"`) entries are excluded from the PDF check entirely

### `TestHasCritical` (4 tests)
- No anomalies → `has_critical=False`
- Only warning anomalies → `has_critical=False`
- Any critical anomaly → `has_critical=True`
- `form_count_drop` specifically sets `has_critical=True`

### `TestMultipleAnomalies` (2 tests)
- Two independent checks both fire, `anomaly_count >= 2`, `has_critical=True` from the critical one
- Worst-case scenario: all three thresholds set to zero so all six checks fire simultaneously

---

## `courtaccess/monitoring/tests/test_drift.py` — 55 tests
**File tested:** `courtaccess/monitoring/drift.py`

### `TestComputeStats` (13 tests)
Directly unit-tests the private `_compute_stats` helper:
- Empty list → all-zero dict with all six keys
- Single value → correct mean, median, min, max, std_dev=0
- Two values → even-count median = average of both
- Three values → odd-count median = middle element
- Five values → odd-count median
- Four values → even-count median
- Mean rounded to 2 decimal places
- Mean with repeating decimal rounded correctly
- Std dev rounded to 2 decimal places
- All same values → std_dev=0
- Two-value std dev computed correctly
- Min and max from an unsorted list
- Large list (100 values) count, mean, min, max

### `TestEmptyCatalog` (3 tests)
- Empty catalog returns early with `total_active=0`, `slices={}`, `bias_flags=[]`
- Thresholds are still present in the output even on early return
- Catalog containing only non-active forms is treated as empty

### `TestOutputContract` (7 tests)
- Top-level keys: `total_active_forms`, `slices`, `bias_flags`, `bias_count`, `thresholds`
- Slices keys: `by_division`, `by_language`, `by_section_heading`, `by_version`
- `by_language` contains `English`, `Spanish`, `Portuguese`
- English coverage is always `100.0`
- `total_active_forms` counts only active entries
- `bias_count == len(bias_flags)`
- Explicit threshold params reflected exactly in output thresholds

### `TestDivisionSlice` (7 tests)
- Single division form count
- Multiple divisions present in slice
- Form appearing in two divisions counted once per division
- Forms with no appearances do not appear in division slice
- ES coverage percentage computed correctly (1 of 2 = 50%)
- PT coverage percentage computed correctly
- Forms with no versions have 0 ES and PT coverage

### `TestUnderservedDivisionFlag` (3 tests)
- Equal-count divisions → no `underserved_division` flags
- Division with form count below 50% of the mean → flagged (uses 10+10+1 pattern)
- Underserved flag severity is `"WARNING"`

### `TestLowTranslationCoverage` (4 tests)
- Division with 0% ES translation → `low_translation_coverage` flag for Spanish
- Division with 0% PT translation → `low_translation_coverage` flag for Portuguese
- Division with 100% ES and PT translations → no coverage flags
- Coverage flags severity is `"WARNING"`

### `TestLanguageCoverageGap` (6 tests)
- ES=50%, PT=40% (gap=10% < 30% threshold) → no flag
- ES=80%, PT=10% (gap=70% > 30% threshold) → `language_coverage_gap` flag
- When ES > PT the flag slice names Spanish as the higher language
- When PT > ES the flag slice names Portuguese as the higher language
- Equal ES and PT coverage → no gap flag
- Gap flag severity is `"WARNING"`

### `TestSectionHeadingSlice` (5 tests)
- Single section heading counted correctly
- Multiple section headings present in slice
- ES and PT coverage percentage per section computed correctly
- Missing `section_heading` key falls back to `"Unknown"`
- `stats` key present in `by_section_heading`

### `TestVersionStats` (3 tests)
- `multi_version_forms` counts forms with `current_version > 1`
- All single-version forms → `multi_version_forms=0`
- `by_version.stats` contains `count`, `mean`, `std_dev`

### `TestLanguageOverallCoverage` (4 tests)
- No translations → 0% Spanish and Portuguese coverage
- All translated → 100% for both
- Partial coverage rounded to 1 decimal place
- Forms with no versions do not contribute to translation counts

---

---

# DB

> **All 163 tests are pure unit tests. No real PostgreSQL connection is made. Async functions use `AsyncMock`, sync functions use `MagicMock`.**

## Infrastructure

### `db/tests/__init__.py`
Empty package marker.

### `db/tests/conftest.py`
Sets dummy `POSTGRES_*` env vars at the top of the module (before any `db.*` import) so `db/database.py`'s module-level `create_async_engine` call receives non-`None` values. Provides three shared fixtures:
- `mock_db` — fully configured `AsyncMock` session with chained result mock supporting `scalar_one_or_none`, `scalar_one`, `scalars().all()`
- `mock_sync_session` — `MagicMock` sync session for Airflow DAG tests
- `mock_sync_conn` — `MagicMock` connection for `write_audit_sync` tests

---

## `db/tests/test_database.py` — 22 tests
**File tested:** `db/database.py`

### `TestMakeAsyncUrl` (6 tests)
- Assembles the full `postgresql+asyncpg://user:pass@host:port/db` URL from env vars
- URL always starts with `postgresql+asyncpg://`
- `POSTGRES_PORT` defaults to `5432` when absent
- Custom port is used when `POSTGRES_PORT` is set
- Host appears in the URL
- DB name is at the end of the URL

### `TestMakeSyncUrl` (4 tests)
- Result contains `psycopg2` and does not contain `asyncpg`
- Result equals `_make_async_url()` with driver replaced
- Starts with `postgresql+psycopg2://`
- Host and DB name are preserved after driver replacement

### `TestMakeDebug` (8 tests)
- `DEBUG` not set → `False`
- `DEBUG=false` → `False`
- `DEBUG=true` (lowercase) → `True`
- `DEBUG=TRUE` (uppercase) → `True`
- `DEBUG=True` (mixed case) → `True`
- `DEBUG=1` → `False` (only the string `"true"` is accepted)
- `DEBUG=yes` → `False`
- Return type is `bool`

### `TestModuleLevelConstants` (4 tests)
- `SYNC_DATABASE_URL` contains `psycopg2` and not `asyncpg`
- `SYNC_DATABASE_URL` is a `str`
- `engine` is an `AsyncEngine` instance
- `AsyncSessionLocal` is callable

### `TestGetSyncEngine` (3 tests)
- Returns a `sqlalchemy.engine.Engine` instance
- Calling twice returns the same object (`lru_cache` identity)
- Engine URL contains `psycopg2`

---

## `db/tests/test_models.py` — 47 tests
**File tested:** `db/models.py`

### `TestTableNames` (11 tests)
Verifies `__tablename__` for all 11 models: `roles`, `users`, `role_requests`, `sessions`, `document_translation_requests`, `realtime_translation_requests`, `audit_logs`, `form_catalog`, `form_versions`, `form_appearances`, `pipeline_steps`.

### `TestRepresentations` (10 tests)
Verifies `__repr__` for all models that define it contains the class name and key identifying fields:
- `Role` → contains role_id and role_name
- `User` → contains email
- `RoleRequest` → contains status
- `Session` → contains type and status
- `DocumentTranslationRequest` → contains status
- `RealtimeTranslationRequest` → contains phase
- `AuditLog` → contains action_type
- `FormCatalog` → contains form_name
- `FormVersion` → contains version number
- `FormAppearance` → contains division

### `TestModelInstantiation` (11 tests)
Constructs each of the 11 models with keyword arguments and asserts fields are set correctly. Verifies optional fields like `file_path_es`, `file_path_pt` default to `None` when not provided.

### `TestRelationships` (14 tests)
Asserts all declared relationship attribute names exist on the model classes:
- `Role.users`, `User.sessions`, `User.audit_logs`
- `Session.document_request`, `Session.realtime_request`, `Session.pipeline_steps`
- `FormCatalog.versions`, `FormCatalog.appearances`
- `FormVersion.form`, `FormAppearance.form`
- `AuditLog.user`, `AuditLog.session`, `AuditLog.document_request`, `AuditLog.realtime_request`

### `TestColumnAttributes` (13 tests)
Spot-checks that key columns are declared on their models: `needs_human_review`, `preprocessing_flags`, `file_path_es/pt`, `firebase_uid`, `mfa_enabled`, `room_code`, `consent_acknowledged`, `step_metadata`, `pii_findings_count`, `signed_url`, `doc_request_id`, `rt_request_id`.

---

## `db/tests/test_queries_audit.py` — 23 tests
**File tested:** `db/queries/audit.py`

### `TestWriteAudit` — 14 async tests
All tests use the `mock_db` fixture (mocked `AsyncSession`):
- `db.add` called exactly once
- Added object is an `AuditLog` instance
- `db.commit` is **NOT** called (caller owns the transaction)
- `user_id` set correctly on the log
- `action_type` set correctly
- `details=None` defaults to `{}`
- `details` dict passed through unchanged
- `session_id` defaults to `None`
- `session_id` forwarded when provided
- `doc_request_id` forwarded when provided
- `rt_request_id` forwarded when provided
- `doc_request_id` and `rt_request_id` default to `None`
- Each call produces a distinct `audit_id` (UUID)
- `audit_id` is a `uuid.UUID` instance

### `TestWriteAuditSync` — 9 tests
All tests use the `mock_sync_conn` fixture (mocked `Connection`):
- `conn.execute` called exactly once
- `conn.commit` **NOT** called
- `action_type` present in the params dict
- `user_id` present in the params dict
- `details` is JSON-serialised before passing to SQL
- `audit_id` is a valid UUID string
- `session_id` defaults to `None`
- `session_id` forwarded when provided
- Consecutive calls produce unique `audit_id` values

---

## `db/tests/test_queries_forms.py` — 68 tests
**File tested:** `db/queries/forms.py`

### `TestUpsertFormCatalog` (5 async tests)
- `execute` and `flush` each called once
- Returns the ORM object from `db.get`
- Returns `None` when `db.get` returns `None`
- `commit` NOT called
- `created_at` excluded from conflict update set (no exception when entry includes `created_at`)

### `TestUpsertFormVersion` (6 async tests)
- `execute` called twice (INSERT + SELECT), `flush` once
- Returns the `scalar_one_or_none` result
- Returns `None` when version not found
- `version_id` auto-generated (UUID4) when absent from `version_dict`
- Provided `version_id` is used when given
- `commit` NOT called

### `TestUpsertFormAppearance` (3 async tests)
- `execute` and `flush` each called once
- Returns `None`
- `commit` NOT called

### `TestUpdateFormVersionTranslations` (3 async tests)
- `execute` and `flush` each called once
- `commit` NOT called
- Returns `None`

### `TestUpdateFormCatalogFields` (4 async tests)
- `execute` and `flush` each called once
- `commit` NOT called
- Returns `None`
- Accepts multiple keyword arguments

### `TestGetFormById` (4 async tests)
- Returns `None` when `scalar_one_or_none` returns `None`
- Returns the form object when found
- `execute` called once
- `commit` NOT called

### `TestListForms` (11 async tests)
- Returns a `(list, int)` tuple
- `execute` called twice (count query then data query)
- Total comes from first execute's `scalar_one()`
- Forms come from second execute's `scalars().all()`
- Empty results: forms=`[]`, total=`0`
- `commit` NOT called
- `status=None` removes status filter without error
- `division`, `language="es"`, `language="pt"`, and `q` filters all accepted

### `TestListDivisions` (5 async tests)
- Returns a `list`
- Returns the division strings from the query result
- Empty when no divisions exist
- `execute` called once
- `commit` NOT called

### `TestSubmitFormReview` (10 async tests)
- Returns `None` when `db.get` returns `None` (form not found)
- `db.add` NOT called when form not found
- `approved=True` sets `form.needs_human_review = False`
- `approved=False` sets `form.needs_human_review = True`
- `db.add` called once (with `AuditLog`)
- Added object's `action_type` is `"form_review_submitted"`
- Added object's `user_id` is the `reviewer_user_id`
- Returns the updated form object on success
- `flush` called once
- `commit` NOT called
- `notes` value appears in audit log `details`

### Sync variant tests (18 tests across 6 classes)

**`TestUpsertFormCatalogSync`** (3): execute+flush called; returns form from `session.get`; no commit.

**`TestUpsertFormVersionSync`** (4): execute+flush called; returns `query().filter().one_or_none()`; auto-generates `version_id` when absent; no commit.

**`TestUpsertFormAppearanceSync`** (3): execute+flush called; returns `None`; no commit.

**`TestGetFormByIdSync`** (3): returns `None` when not found; returns form when found; execute called once.

**`TestUpdateFormVersionTranslationsSync`** (2): execute+flush called; no commit.

**`TestUpdateFormCatalogFieldsSync`** (2): execute+flush called; no commit.

### `TestGetAllFormsSync` (5 tests)
Uses `patch("db.database.get_sync_engine")` (patched at the import source, not the call site) and `patch("sqlalchemy.orm.Session")`:
- Returns a `list`
- Returns `[]` when no forms in DB
- Output dict has all required keys: `form_id`, `form_name`, `form_slug`, `source_url`, `file_type`, `status`, `content_hash`, `current_version`, `needs_human_review`, `created_at`, `appearances`, `versions`
- `form_id` is serialised to `str`
- Versions are sorted descending by version number (highest first)
