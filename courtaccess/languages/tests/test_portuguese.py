"""
Tests for courtaccess/languages/portuguese.py

Verifies PORTUGUESE_CONFIG values: identity, NLLB codes, court name
translations, legal overrides, form token translations, skip lines,
and production readiness.
"""

from courtaccess.languages.portuguese import PORTUGUESE_CONFIG

# ══════════════════════════════════════════════════════════════════════════════
# Identity
# ══════════════════════════════════════════════════════════════════════════════


def test_code():
    assert PORTUGUESE_CONFIG.code == "portuguese"


def test_display_name_contains_portuguese():
    assert "Portuguese" in PORTUGUESE_CONFIG.display_name


def test_display_name_contains_portugues():
    assert "Português" in PORTUGUESE_CONFIG.display_name


def test_llama_lang_label():
    assert PORTUGUESE_CONFIG.llama_lang_label == "Portuguese"


def test_ready_for_production():
    assert PORTUGUESE_CONFIG.ready_for_production is True


# ══════════════════════════════════════════════════════════════════════════════
# NLLB codes
# ══════════════════════════════════════════════════════════════════════════════


def test_nllb_source():
    assert PORTUGUESE_CONFIG.nllb_source == "eng_Latn"


def test_nllb_target():
    assert PORTUGUESE_CONFIG.nllb_target == "por_Latn"


# ══════════════════════════════════════════════════════════════════════════════
# Glossary path
# ══════════════════════════════════════════════════════════════════════════════


def test_glossary_path_points_to_pt_file():
    assert "pt" in PORTUGUESE_CONFIG.glossary_path
    assert PORTUGUESE_CONFIG.glossary_path.endswith(".json")


# ══════════════════════════════════════════════════════════════════════════════
# Court name translations
# ══════════════════════════════════════════════════════════════════════════════


def test_court_name_translations_not_empty():
    assert len(PORTUGUESE_CONFIG.court_name_translations) > 0


def test_massachusetts_trial_court_translated():
    assert "Massachusetts Trial Court" in PORTUGUESE_CONFIG.court_name_translations
    assert (
        PORTUGUESE_CONFIG.court_name_translations["Massachusetts Trial Court"]
        == "Tribunal de Julgamento de Massachusetts"
    )


def test_district_court_translated():
    assert "District Court" in PORTUGUESE_CONFIG.court_name_translations


def test_superior_court_translated():
    assert "Superior Court" in PORTUGUESE_CONFIG.court_name_translations


def test_housing_court_translated():
    assert "Housing Court" in PORTUGUESE_CONFIG.court_name_translations


def test_juvenile_court_translated():
    assert "Juvenile Court" in PORTUGUESE_CONFIG.court_name_translations


def test_appeals_court_translated():
    assert "Appeals Court" in PORTUGUESE_CONFIG.court_name_translations


def test_supreme_judicial_court_translated():
    assert "Supreme Judicial Court" in PORTUGUESE_CONFIG.court_name_translations


def test_land_court_translated():
    assert "Land Court" in PORTUGUESE_CONFIG.court_name_translations


def test_court_name_translations_values_are_strings():
    for k, v in PORTUGUESE_CONFIG.court_name_translations.items():
        assert isinstance(v, str), f"Translation for '{k}' is not a string"


def test_court_name_translations_no_empty_values():
    for k, v in PORTUGUESE_CONFIG.court_name_translations.items():
        assert v.strip(), f"Translation for '{k}' is empty"


# ══════════════════════════════════════════════════════════════════════════════
# Legal overrides
# ══════════════════════════════════════════════════════════════════════════════


def test_legal_overrides_not_empty():
    assert len(PORTUGUESE_CONFIG.legal_overrides) > 0


def test_defendant_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("defendant") == "réu"


def test_plaintiff_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("plaintiff") == "autor"


def test_beyond_reasonable_doubt_override():
    assert "beyond a reasonable doubt" in PORTUGUESE_CONFIG.legal_overrides


def test_waiver_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("waiver") == "renúncia"


def test_verdict_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("verdict") == "veredito"


def test_counsel_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("counsel") == "advogado"


def test_public_defender_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("public defender") == "defensor público"


def test_commonwealth_preserved():
    assert PORTUGUESE_CONFIG.legal_overrides.get("commonwealth") == "Commonwealth"


def test_juror_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("juror") == "jurado"


def test_due_process_override():
    assert PORTUGUESE_CONFIG.legal_overrides.get("due process") == "devido processo legal"


def test_legal_overrides_keys_are_lowercase():
    for key in PORTUGUESE_CONFIG.legal_overrides:
        assert key == key.lower(), f"Key '{key}' is not lowercase"


def test_legal_overrides_values_are_strings():
    for k, v in PORTUGUESE_CONFIG.legal_overrides.items():
        assert isinstance(v, str), f"Override value for '{k}' is not a string"


# ══════════════════════════════════════════════════════════════════════════════
# Form token translations
# ══════════════════════════════════════════════════════════════════════════════


def test_form_token_translations_not_empty():
    assert len(PORTUGUESE_CONFIG.form_token_translations) > 0


def test_date_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("DATE") == "DATA"


def test_signature_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("SIGNATURE") == "ASSINATURA"


def test_submit_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("SUBMIT") == "ENVIAR"


def test_sign_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("SIGN") == "ASSINAR"


def test_clear_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("CLEAR") == "LIMPAR"


def test_county_token():
    assert PORTUGUESE_CONFIG.form_token_translations.get("COUNTY") == "CONDADO"


def test_form_token_values_are_strings():
    for k, v in PORTUGUESE_CONFIG.form_token_translations.items():
        assert isinstance(v, str), f"Token translation for '{k}' is not a string"


def test_form_token_keys_are_uppercase():
    for key in PORTUGUESE_CONFIG.form_token_translations:
        assert key == key.upper(), f"Token key '{key}' is not uppercase"


# ══════════════════════════════════════════════════════════════════════════════
# Glossary skip lines
# ══════════════════════════════════════════════════════════════════════════════


def test_glossary_skip_lines_not_empty():
    assert len(PORTUGUESE_CONFIG.glossary_skip_lines) > 0


def test_glossary_skip_lines_contains_glossary_header():
    assert "glossary of legal" in PORTUGUESE_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_contains_revised():
    assert "revised" in PORTUGUESE_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_contains_introduction():
    assert "introduction" in PORTUGUESE_CONFIG.glossary_skip_lines


def test_glossary_skip_lines_is_set():
    assert isinstance(PORTUGUESE_CONFIG.glossary_skip_lines, set)


def test_glossary_skip_lines_are_lowercase():
    for line in PORTUGUESE_CONFIG.glossary_skip_lines:
        assert line == line.lower(), f"Skip line '{line}' is not lowercase"


# ══════════════════════════════════════════════════════════════════════════════
# Spanish vs Portuguese differences
# ══════════════════════════════════════════════════════════════════════════════


def test_nllb_targets_differ_from_spanish():
    from courtaccess.languages.spanish import SPANISH_CONFIG

    assert PORTUGUESE_CONFIG.nllb_target != SPANISH_CONFIG.nllb_target


def test_defendant_translation_differs_from_spanish():
    from courtaccess.languages.spanish import SPANISH_CONFIG

    assert PORTUGUESE_CONFIG.legal_overrides["defendant"] != SPANISH_CONFIG.legal_overrides["defendant"]


def test_date_token_differs_from_spanish():
    from courtaccess.languages.spanish import SPANISH_CONFIG

    assert PORTUGUESE_CONFIG.form_token_translations["DATE"] != SPANISH_CONFIG.form_token_translations["DATE"]


def test_sign_token_differs_from_spanish():
    from courtaccess.languages.spanish import SPANISH_CONFIG

    assert PORTUGUESE_CONFIG.form_token_translations["SIGN"] != SPANISH_CONFIG.form_token_translations["SIGN"]
