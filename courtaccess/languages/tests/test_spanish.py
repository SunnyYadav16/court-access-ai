"""
Tests for courtaccess/languages/spanish.py

Verifies SPANISH_CONFIG values: identity, NLLB codes, court name
translations, legal overrides, form token translations, skip lines,
and production readiness.
"""

from courtaccess.languages.spanish import SPANISH_CONFIG

# ══════════════════════════════════════════════════════════════════════════════
# Identity
# ══════════════════════════════════════════════════════════════════════════════


def test_code():
    assert SPANISH_CONFIG.code == "spanish"


def test_display_name_contains_spanish():
    assert "Spanish" in SPANISH_CONFIG.display_name


def test_display_name_contains_espanol():
    assert "Español" in SPANISH_CONFIG.display_name


def test_llama_lang_label():
    assert SPANISH_CONFIG.llama_lang_label == "Spanish"


def test_ready_for_production():
    assert SPANISH_CONFIG.ready_for_production is True


# ══════════════════════════════════════════════════════════════════════════════
# NLLB codes
# ══════════════════════════════════════════════════════════════════════════════


def test_nllb_source():
    assert SPANISH_CONFIG.nllb_source == "eng_Latn"


def test_nllb_target():
    assert SPANISH_CONFIG.nllb_target == "spa_Latn"


# ══════════════════════════════════════════════════════════════════════════════
# Glossary path
# ══════════════════════════════════════════════════════════════════════════════


def test_glossary_path_points_to_es_file():
    assert "es" in SPANISH_CONFIG.glossary_path
    assert SPANISH_CONFIG.glossary_path.endswith(".json")


# ══════════════════════════════════════════════════════════════════════════════
# Court name translations
# ══════════════════════════════════════════════════════════════════════════════


def test_court_name_translations_is_not_empty():
    assert len(SPANISH_CONFIG.court_name_translations) > 0


def test_massachusetts_trial_court_translated():
    assert "Massachusetts Trial Court" in SPANISH_CONFIG.court_name_translations
    assert SPANISH_CONFIG.court_name_translations["Massachusetts Trial Court"] == "Tribunal de Justicia de Massachusetts"


def test_district_court_translated():
    assert "District Court" in SPANISH_CONFIG.court_name_translations


def test_superior_court_translated():
    assert "Superior Court" in SPANISH_CONFIG.court_name_translations


def test_housing_court_translated():
    assert "Housing Court" in SPANISH_CONFIG.court_name_translations


def test_juvenile_court_translated():
    assert "Juvenile Court" in SPANISH_CONFIG.court_name_translations


def test_appeals_court_translated():
    assert "Appeals Court" in SPANISH_CONFIG.court_name_translations


def test_supreme_judicial_court_translated():
    assert "Supreme Judicial Court" in SPANISH_CONFIG.court_name_translations


def test_court_name_translations_values_are_strings():
    for k, v in SPANISH_CONFIG.court_name_translations.items():
        assert isinstance(v, str), f"Translation for '{k}' is not a string"


def test_court_name_translations_no_empty_values():
    for k, v in SPANISH_CONFIG.court_name_translations.items():
        assert v.strip(), f"Translation for '{k}' is empty"


# ══════════════════════════════════════════════════════════════════════════════
# Legal overrides
# ══════════════════════════════════════════════════════════════════════════════


def test_legal_overrides_not_empty():
    assert len(SPANISH_CONFIG.legal_overrides) > 0


def test_defendant_override():
    assert SPANISH_CONFIG.legal_overrides.get("defendant") == "acusado"


def test_plaintiff_override():
    assert SPANISH_CONFIG.legal_overrides.get("plaintiff") == "demandante"


def test_beyond_reasonable_doubt_override():
    assert "beyond a reasonable doubt" in SPANISH_CONFIG.legal_overrides


def test_waiver_override():
    assert SPANISH_CONFIG.legal_overrides.get("waiver") == "renuncia"


def test_verdict_override():
    assert SPANISH_CONFIG.legal_overrides.get("verdict") == "veredicto"


def test_counsel_override():
    assert SPANISH_CONFIG.legal_overrides.get("counsel") == "abogado"


def test_public_defender_override():
    assert SPANISH_CONFIG.legal_overrides.get("public defender") == "defensor público"


def test_commonwealth_preserved():
    # "commonwealth" should stay as "Commonwealth" (proper noun)
    assert SPANISH_CONFIG.legal_overrides.get("commonwealth") == "Commonwealth"


def test_legal_overrides_keys_are_lowercase():
    for key in SPANISH_CONFIG.legal_overrides:
        assert key == key.lower(), f"Key '{key}' is not lowercase"


def test_legal_overrides_values_are_strings():
    for k, v in SPANISH_CONFIG.legal_overrides.items():
        assert isinstance(v, str), f"Override value for '{k}' is not a string"


# ══════════════════════════════════════════════════════════════════════════════
# Form token translations
# ══════════════════════════════════════════════════════════════════════════════


def test_form_token_translations_not_empty():
    assert len(SPANISH_CONFIG.form_token_translations) > 0


def test_date_token():
    assert SPANISH_CONFIG.form_token_translations.get("DATE") == "FECHA"


def test_signature_token():
    assert SPANISH_CONFIG.form_token_translations.get("SIGNATURE") == "FIRMA"


def test_submit_token():
    assert SPANISH_CONFIG.form_token_translations.get("SUBMIT") == "ENVIAR"


def test_sign_token():
    assert SPANISH_CONFIG.form_token_translations.get("SIGN") == "FIRMAR"


def test_county_token():
    assert SPANISH_CONFIG.form_token_translations.get("COUNTY") == "CONDADO"


def test_form_token_values_are_strings():
    for k, v in SPANISH_CONFIG.form_token_translations.items():
        assert isinstance(v, str), f"Token translation for '{k}' is not a string"


def test_form_token_keys_are_uppercase():
    for key in SPANISH_CONFIG.form_token_translations:
        assert key == key.upper(), f"Token key '{key}' is not uppercase"


# ══════════════════════════════════════════════════════════════════════════════
# Glossary skip lines
# ══════════════════════════════════════════════════════════════════════════════


def test_glossary_skip_lines_not_empty():
    assert len(SPANISH_CONFIG.glossary_skip_lines) > 0


def test_glossary_skip_lines_contains_glossary_header():
    assert "glossary of legal" in SPANISH_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_contains_revised():
    assert "revised" in SPANISH_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_contains_introduction():
    assert "introduction" in SPANISH_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_is_set():
    assert isinstance(SPANISH_CONFIG.glossary_skip_lines, set)


def test_glossary_skip_lines_are_lowercase():
    for line in SPANISH_CONFIG.glossary_skip_lines:
        assert line == line.lower(), f"Skip line '{line}' is not lowercase"
