"""
Tests for courtaccess/languages/base.py

Covers the LanguageConfig dataclass defaults, __post_init__ logic,
and field types.
"""

from courtaccess.languages.base import LanguageConfig


def _minimal_config(**overrides) -> LanguageConfig:
    """Create a minimal valid LanguageConfig with sensible defaults."""
    defaults = dict(
        code="test",
        display_name="Test Language",
        nllb_source="eng_Latn",
        nllb_target="tst_Latn",
        glossary_path="data/glossaries/glossary_test.json",
    )
    defaults.update(overrides)
    return LanguageConfig(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# Field defaults
# ══════════════════════════════════════════════════════════════════════════════


def test_default_court_name_translations_is_empty_dict():
    config = _minimal_config()
    assert config.court_name_translations == {}


def test_default_legal_overrides_is_empty_dict():
    config = _minimal_config()
    assert config.legal_overrides == {}


def test_default_form_token_translations_is_empty_dict():
    config = _minimal_config()
    assert config.form_token_translations == {}


def test_default_glossary_skip_lines_is_empty_set():
    config = _minimal_config()
    assert config.glossary_skip_lines == set()


def test_default_ready_for_production_is_true():
    config = _minimal_config()
    assert config.ready_for_production is True


def test_default_llama_lang_label_empty_string_before_post_init():
    """After __post_init__, llama_lang_label defaults to display_name."""
    config = _minimal_config()
    assert config.llama_lang_label == config.display_name


# ══════════════════════════════════════════════════════════════════════════════
# __post_init__: llama_lang_label behaviour
# ══════════════════════════════════════════════════════════════════════════════


def test_llama_lang_label_defaults_to_display_name():
    config = _minimal_config(display_name="My Language")
    assert config.llama_lang_label == "My Language"


def test_explicit_llama_lang_label_is_preserved():
    config = _minimal_config(llama_lang_label="Explicit Label")
    assert config.llama_lang_label == "Explicit Label"


def test_explicit_llama_lang_label_not_overwritten_by_display_name():
    config = _minimal_config(display_name="Display", llama_lang_label="Custom")
    assert config.llama_lang_label == "Custom"


# ══════════════════════════════════════════════════════════════════════════════
# ready_for_production
# ══════════════════════════════════════════════════════════════════════════════


def test_ready_for_production_can_be_false():
    config = _minimal_config(ready_for_production=False)
    assert config.ready_for_production is False


def test_ready_for_production_can_be_true():
    config = _minimal_config(ready_for_production=True)
    assert config.ready_for_production is True


# ══════════════════════════════════════════════════════════════════════════════
# Field types
# ══════════════════════════════════════════════════════════════════════════════


def test_code_is_string():
    config = _minimal_config(code="es")
    assert isinstance(config.code, str)


def test_display_name_is_string():
    config = _minimal_config(display_name="Español")
    assert isinstance(config.display_name, str)


def test_nllb_source_is_string():
    config = _minimal_config()
    assert isinstance(config.nllb_source, str)


def test_nllb_target_is_string():
    config = _minimal_config()
    assert isinstance(config.nllb_target, str)


def test_glossary_path_is_string():
    config = _minimal_config()
    assert isinstance(config.glossary_path, str)


def test_court_name_translations_is_dict():
    config = _minimal_config(court_name_translations={"District Court": "Tribunal Distrital"})
    assert isinstance(config.court_name_translations, dict)


def test_legal_overrides_is_dict():
    config = _minimal_config(legal_overrides={"plea": "declaración"})
    assert isinstance(config.legal_overrides, dict)


def test_form_token_translations_is_dict():
    config = _minimal_config(form_token_translations={"DATE": "FECHA"})
    assert isinstance(config.form_token_translations, dict)


def test_glossary_skip_lines_is_set():
    config = _minimal_config(glossary_skip_lines={"revised", "introduction"})
    assert isinstance(config.glossary_skip_lines, set)


# ══════════════════════════════════════════════════════════════════════════════
# Mutable default isolation — each instance gets its own dict/set
# ══════════════════════════════════════════════════════════════════════════════


def test_mutable_defaults_are_isolated():
    config1 = _minimal_config()
    config2 = _minimal_config()

    config1.court_name_translations["Key"] = "Value"
    assert "Key" not in config2.court_name_translations


def test_mutable_skip_lines_are_isolated():
    config1 = _minimal_config()
    config2 = _minimal_config()

    config1.glossary_skip_lines.add("new skip")
    assert "new skip" not in config2.glossary_skip_lines


# ══════════════════════════════════════════════════════════════════════════════
# Populated fields
# ══════════════════════════════════════════════════════════════════════════════


def test_all_required_fields_stored():
    config = LanguageConfig(
        code="fr",
        display_name="French (Français)",
        nllb_source="eng_Latn",
        nllb_target="fra_Latn",
        glossary_path="data/glossaries/glossary_fr.json",
        court_name_translations={"District Court": "Tribunal de District"},
        legal_overrides={"defendant": "accusé"},
        form_token_translations={"DATE": "DATE"},
        glossary_skip_lines={"introduction"},
        llama_lang_label="French",
        ready_for_production=False,
    )
    assert config.code == "fr"
    assert config.display_name == "French (Français)"
    assert config.nllb_source == "eng_Latn"
    assert config.nllb_target == "fra_Latn"
    assert config.glossary_path == "data/glossaries/glossary_fr.json"
    assert config.court_name_translations == {"District Court": "Tribunal de District"}
    assert config.legal_overrides == {"defendant": "accusé"}
    assert config.form_token_translations == {"DATE": "DATE"}
    assert config.glossary_skip_lines == {"introduction"}
    assert config.llama_lang_label == "French"
    assert config.ready_for_production is False
