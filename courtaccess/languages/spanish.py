"""
courtaccess/languages/spanish.py

Spanish language configuration.
Values extracted from Cell 6 and Cell 7 of the original Colab script.
"""

from courtaccess.languages.base import LanguageConfig

SPANISH_CONFIG = LanguageConfig(
    code="spanish",
    display_name="Spanish (Español)",
    nllb_source="eng_Latn",
    nllb_target="spa_Latn",
    glossary_path="data/glossaries/glossary_es.json",
    llama_lang_label="Spanish",
    # ── Court name translations ───────────────────────────────────────────
    # Sorted longest-first to prevent partial matches
    # Source: Cell 6 COURT_NAME_TRANSLATIONS in Colab script
    court_name_translations={
        "Massachusetts Trial Court": "Tribunal de Justicia de Massachusetts",
        "Supreme Judicial Court": "Tribunal Supremo Judicial",
        "Boston Municipal Court": "Tribunal Municipal de Boston",
        "Land Court Department": "Departamento del Tribunal de Tierras",
        "District Court": "Tribunal de Distrito",
        "Superior Court": "Tribunal Superior",
        "Appeals Court": "Tribunal de Apelaciones",
        "Housing Court": "Tribunal de Vivienda",
        "Juvenile Court": "Tribunal de Menores",
        "Probate Court": "Tribunal de Sucesiones",
        "Trial Court": "Tribunal de Justicia",
        "Land Court": "Tribunal de Tierras",
        "Lower Court": "Tribunal Inferior",
    },
    # ── Legal term overrides ──────────────────────────────────────────────
    # Source: Cell 7a MA_OVERRIDES_ES in Colab script
    legal_overrides={
        "commonwealth": "Commonwealth",
        "beyond a reasonable doubt": "más allá de una duda razonable",
        "mandatory minimum": "mínimo obligatorio",
        "waiver": "renuncia",
        "waive": "renunciar",
        "plea": "declaración",
        "defendant": "acusado",
        "plaintiff": "demandante",
        "juror": "miembro del jurado",
        "right to counsel": "derecho a la asistencia letrada",
        "due process": "debido proceso",
        "contempt": "desacato",
        "counsel": "abogado",
        "public defender": "defensor público",
        "verdict": "veredicto",
        "party": "parte",
        "party(s)": "parte(s)",
        "notice": "aviso",
        "partition": "partición",
        "child": "menor",
    },
    form_token_translations={
        "DATE": "FECHA",
        "SIGNATURE": "FIRMA",
        "PRINT": "IMPRIMIR",
        "CLEAR": "BORRAR",
        "SUBMIT": "ENVIAR",
        "COUNTY": "CONDADO",
        "SIGN": "FIRMAR",
    },
    glossary_skip_lines={
        "glossary of legal",
        "revised",
        "revisado",
        "cn 11783",
        "a , b , c",
        "introduction",
        "the primary purpose",
        "this document",
        "the glossary is not",
        "wrong and unacceptable",
        "one correct way",
        "benefit.",
        "for all the only",
        "promote uniform",
        "when working on",
        "issues official",
        "updated each time",
    },
)
