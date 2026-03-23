"""
courtaccess/languages/portuguese.py

Portuguese (Brazilian) language configuration.
Values extracted from Cell 6 and Cell 7 of the original Colab script.
"""

from courtaccess.languages.base import LanguageConfig

PORTUGUESE_CONFIG = LanguageConfig(
    code="portuguese",
    display_name="Portuguese (Português)",
    nllb_source="eng_Latn",
    nllb_target="por_Latn",
    glossary_path="data/glossaries/glossary_pt.json",
    llama_lang_label="Portuguese",
    # ── Court name translations ───────────────────────────────────────────
    # Sorted longest-first to prevent partial matches
    # Source: Cell 6 COURT_NAME_TRANSLATIONS in Colab script
    court_name_translations={
        "Massachusetts Trial Court": "Tribunal de Julgamento de Massachusetts",
        "Land Court Department": "Departamento do Tribunal de Terras",
        "Supreme Judicial Court": "Supremo Tribunal Judicial",
        "Boston Municipal Court": "Tribunal Municipal de Boston",
        "District Court": "Tribunal Distrital",
        "Superior Court": "Tribunal Superior",
        "Appeals Court": "Tribunal de Recursos",
        "Housing Court": "Tribunal de Habitação",
        "Juvenile Court": "Tribunal de Menores",
        "Probate Court": "Tribunal de Sucessões",
        "Trial Court": "Tribunal de Julgamento",
        "Land Court": "Tribunal de Terras",
        "Lower Court": "Tribunal Inferior",
    },
    # ── Legal term overrides ──────────────────────────────────────────────
    # Source: Cell 7a MA_OVERRIDES_PT in Colab script
    legal_overrides={
        "commonwealth": "Commonwealth",
        "g.l. c.": "G.L. c.",
        "beyond a reasonable doubt": "culpa acima de qualquer suspeita razoável",
        "mandatory minimum": "mínimo obrigatório",
        "municipal court": "Tribunal Municipal",
        "waiver": "renúncia",
        "waive": "renunciar",
        "plea": "declaração",
        "defendant": "réu",
        "plaintiff": "autor",
        "juror": "jurado",
        "right to counsel": "direito à assistência jurídica",
        "due process": "devido processo legal",
        "contempt": "desacato",
        "counsel": "advogado",
        "public defender": "defensor público",
        "verdict": "veredito",
        "trial court": "tribunal de primeira instância",
        "party": "parte",
        "party(s)": "parte(s)",
        "notice": "aviso, notificação",
        "partition": "partilha",
        "child": "menor",
    },
    form_token_translations={
        "DATE": "DATA",
        "SIGNATURE": "ASSINATURA",
        "PRINT": "IMPRIMIR",
        "CLEAR": "LIMPAR",
        "SUBMIT": "ENVIAR",
        "COUNTY": "CONDADO",
        "SIGN": "ASSINAR",
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
