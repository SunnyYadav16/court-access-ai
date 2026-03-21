"""
courtaccess/languages/portuguese.py

Portuguese (Brazilian) language configuration.

STATUS: STUB — court name translations, legal overrides, and form tokens
are placeholders. Full values will be added when the Portuguese
Colab script is provided.

DO NOT use USE_REAL_TRANSLATION=true with Portuguese until this is complete.
"""

from courtaccess.languages.base import LanguageConfig

PORTUGUESE_CONFIG = LanguageConfig(
    code="portuguese",
    display_name="Portuguese (Português)",
    nllb_source="eng_Latn",
    nllb_target="por_Latn",
    glossary_path="data/glossaries/glossary_pt.json",
    llama_lang_label="Portuguese",
    # Stub config — court names, legal overrides, and form tokens are
    # placeholders. Set to True only after real values are supplied.
    ready_for_production=False,
    # ── STUB — to be filled from Portuguese Colab script ─────
    court_name_translations={
        "Massachusetts Trial Court": "[PT STUB]",
        "Land Court Department": "[PT STUB]",
        "Boston Municipal Court": "[PT STUB]",
        "Supreme Judicial Court": "[PT STUB]",
        "Land Court": "[PT STUB]",
        "District Court": "[PT STUB]",
        "Superior Court": "[PT STUB]",
        "Appeals Court": "[PT STUB]",
        "Housing Court": "[PT STUB]",
        "Juvenile Court": "[PT STUB]",
        "Probate Court": "[PT STUB]",
        "Trial Court": "[PT STUB]",
        "Lower Court": "[PT STUB]",
    },
    # ── STUB ──────────────────────────────────────────────────
    legal_overrides={
        "commonwealth": "[PT STUB]",
        "beyond a reasonable doubt": "[PT STUB]",
        "mandatory minimum": "[PT STUB]",
        "waiver": "[PT STUB]",
        "defendant": "[PT STUB]",
        "plaintiff": "[PT STUB]",
        "counsel": "[PT STUB]",
        "verdict": "[PT STUB]",
    },
    # ── STUB ──────────────────────────────────────────────────
    form_token_translations={
        "DATE": "[PT STUB]",
        "SIGNATURE": "[PT STUB]",
        "PRINT": "[PT STUB]",
        "CLEAR": "[PT STUB]",
        "SUBMIT": "[PT STUB]",
        "COUNTY": "[PT STUB]",
        "SIGN": "[PT STUB]",
    },
    # ── STUB — to be filled from Portuguese Colab script ─────────
    glossary_skip_lines=set(),
)
