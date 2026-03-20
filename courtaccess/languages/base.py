"""
courtaccess/languages/base.py

Base language configuration dataclass.
All language configs inherit from LanguageConfig.

Adding a new language = create a new file in courtaccess/languages/,
subclass LanguageConfig, fill in the values. Nothing else changes.
"""

from dataclasses import dataclass, field


@dataclass
class LanguageConfig:
    # ── Identity ──────────────────────────────────────────────────────────
    code: str                    # short code used in API: "spanish" | "portuguese"
    display_name: str            # shown in UI: "Spanish (Español)"

    # ── NLLB language codes ───────────────────────────────────────────────
    nllb_source: str             # always "eng_Latn" for our use case
    nllb_target: str             # "spa_Latn" | "por_Latn"

    # ── Glossary ──────────────────────────────────────────────────────────
    glossary_path: str           # path to data/glossaries/glossary_xx.json

    # ── Court name translations ───────────────────────────────────────────
    # Longest first — matched before NLLB so they're never mistranslated
    court_name_translations: dict = field(default_factory=dict)

    # ── Legal term overrides ──────────────────────────────────────────────
    # Domain-specific terms that generic NLLB gets wrong
    legal_overrides: dict = field(default_factory=dict)

    # ── Form token translations ───────────────────────────────────
    # Single-word form field labels like DATE, SIGNATURE, SIGN
    # Language-specific — Portuguese will fill these in later
    form_token_translations: dict = field(default_factory=dict)

    # ── Glossary skip lines ───────────────────────────────────────
    # Strings to skip when parsing the glossary PDF.
    # Language-specific — NJ Courts PDF has Spanish-specific headers
    # that differ from other glossary sources.
    glossary_skip_lines: set = field(default_factory=set)

    # ── Llama prompt language label ───────────────────────────────────────
    # Used in the Vertex AI verification prompt
    llama_lang_label: str = ""   # "Spanish" | "Portuguese"

    def __post_init__(self):
        # Default llama_lang_label to display_name if not set
        if not self.llama_lang_label:
            self.llama_lang_label = self.display_name
