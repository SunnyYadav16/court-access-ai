"""
Tests for courtaccess/monitoring/drift.py (bias detection)

Coverage:
  - _compute_stats: empty list, single value, two values, even/odd n,
                    rounding, std_dev, all-same values
  - run_bias_detection:
      - Empty / inactive-only catalog early return
      - Output contract (all keys present)
      - Explicit threshold params override env vars
      - Division slice: form counts, ES/PT coverage %
      - Underserved division flag
      - Low translation coverage flags (ES and PT)
      - Language coverage gap flag (ES > PT and PT > ES)
      - No gap when within threshold
      - Section heading slice
      - Version stats (multi_version_forms)
      - bias_count = len(bias_flags)
      - Forms with no appearances not counted in division/section slices
      - Forms with no versions yield 0 ES/PT credit
      - thresholds reflected in output report
"""
from __future__ import annotations

import math

from courtaccess.monitoring.drift import _compute_stats, run_bias_detection

# ── catalog builder helpers ───────────────────────────────────────────────────


def _version(es: str | None = None, pt: str | None = None) -> dict:
    return {"file_path_es": es, "file_path_pt": pt}


def _app(division: str = "Civil", section: str = "General") -> dict:
    return {"division": division, "section_heading": section}


def _form(
    form_id: str = "F001",
    status: str = "active",
    appearances: list | None = None,
    versions: list | None = None,
    current_version: int = 1,
) -> dict:
    return {
        "form_id": form_id,
        "status": status,
        "appearances": appearances or [],
        "versions": versions or [],
        "current_version": current_version,
    }


# ── common threshold kwargs (all explicit — no env reads) ─────────────────────
_T = {"underserved_threshold": 0.5, "translation_coverage_min": 20.0, "language_gap_max": 30.0}


# ══════════════════════════════════════════════════════════════════════════════
# _compute_stats
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeStats:
    def test_empty_list_all_zeros(self):
        s = _compute_stats([])
        assert s == {"count": 0, "mean": 0, "median": 0, "min": 0, "max": 0, "std_dev": 0}

    def test_single_value(self):
        s = _compute_stats([7.0])
        assert s["count"] == 1
        assert s["mean"] == 7.0
        assert s["median"] == 7.0
        assert s["min"] == 7.0
        assert s["max"] == 7.0
        assert s["std_dev"] == 0.0

    def test_two_values_even_median(self):
        s = _compute_stats([2.0, 8.0])
        assert s["count"] == 2
        assert s["mean"] == 5.0
        assert s["median"] == 5.0  # (2+8)/2

    def test_three_values_odd_median(self):
        s = _compute_stats([1.0, 2.0, 3.0])
        assert s["median"] == 2.0

    def test_five_values_odd_median(self):
        s = _compute_stats([10.0, 20.0, 30.0, 40.0, 50.0])
        assert s["median"] == 30.0

    def test_four_values_even_median(self):
        s = _compute_stats([1.0, 3.0, 5.0, 7.0])
        assert s["median"] == 4.0  # (3+5)/2

    def test_mean_rounded_to_2_decimal_places(self):
        s = _compute_stats([1.0, 2.0, 3.0])  # mean = 2.0, already exact
        assert s["mean"] == round(2.0, 2)

    def test_mean_with_repeating_decimal(self):
        # 1+2+3+4+5 = 15 / 5 = 3.0 — exact
        # Let's try 1+1+2 = 4/3 = 1.333...
        s = _compute_stats([1.0, 1.0, 2.0])
        assert s["mean"] == round(4 / 3, 2)

    def test_std_dev_rounded_to_2_decimal_places(self):
        s = _compute_stats([1.0, 2.0, 3.0])
        expected_var = ((1 - 2) ** 2 + (2 - 2) ** 2 + (3 - 2) ** 2) / 3
        expected_std = round(math.sqrt(expected_var), 2)
        assert s["std_dev"] == expected_std

    def test_all_same_values_std_dev_zero(self):
        s = _compute_stats([5.0, 5.0, 5.0])
        assert s["std_dev"] == 0.0

    def test_two_values_std_dev(self):
        s = _compute_stats([2.0, 8.0])
        # variance = ((2-5)^2 + (8-5)^2) / 2 = 9 → std_dev=3.0
        assert s["std_dev"] == 3.0

    def test_min_and_max_correct(self):
        s = _compute_stats([3.0, 1.0, 4.0, 1.0, 5.0])
        assert s["min"] == 1.0
        assert s["max"] == 5.0

    def test_large_list_count(self):
        values = list(range(1, 101))
        s = _compute_stats(values)
        assert s["count"] == 100
        assert s["mean"] == 50.5
        assert s["min"] == 1
        assert s["max"] == 100


# ══════════════════════════════════════════════════════════════════════════════
# run_bias_detection — empty / inactive catalog
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyCatalog:
    def test_empty_catalog_returns_early_structure(self):
        result = run_bias_detection([], **_T)
        assert result["total_active"] == 0
        assert result["slices"] == {}
        assert result["bias_flags"] == []

    def test_empty_catalog_thresholds_in_output(self):
        result = run_bias_detection([], **_T)
        thresholds = result["thresholds"]
        assert thresholds["underserved_division_pct"] == 0.5 * 100
        assert thresholds["translation_coverage_min_pct"] == 20.0
        assert thresholds["language_gap_max_pct"] == 30.0

    def test_only_inactive_forms_treated_as_empty(self):
        catalog = [_form("F001", status="deprecated")]
        result = run_bias_detection(catalog, **_T)
        assert result["total_active"] == 0
        assert result["slices"] == {}


# ══════════════════════════════════════════════════════════════════════════════
# run_bias_detection — output contract
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputContract:
    def _catalog_one(self):
        return [_form("F001", appearances=[_app()], versions=[_version()])]

    def test_top_level_keys_present(self):
        result = run_bias_detection(self._catalog_one(), **_T)
        assert "total_active_forms" in result
        assert "slices" in result
        assert "bias_flags" in result
        assert "bias_count" in result
        assert "thresholds" in result

    def test_slices_keys_present(self):
        result = run_bias_detection(self._catalog_one(), **_T)
        slices = result["slices"]
        assert "by_division" in slices
        assert "by_language" in slices
        assert "by_section_heading" in slices
        assert "by_version" in slices

    def test_by_language_keys(self):
        result = run_bias_detection(self._catalog_one(), **_T)
        lang = result["slices"]["by_language"]["data"]
        assert "English" in lang
        assert "Spanish" in lang
        assert "Portuguese" in lang

    def test_english_coverage_always_100(self):
        result = run_bias_detection(self._catalog_one(), **_T)
        assert result["slices"]["by_language"]["data"]["English"]["coverage_pct"] == 100.0

    def test_total_active_forms_correct(self):
        catalog = [
            _form("F001", appearances=[_app()]),
            _form("F002", appearances=[_app()]),
            _form("F003", status="deprecated", appearances=[_app()]),
        ]
        result = run_bias_detection(catalog, **_T)
        assert result["total_active_forms"] == 2

    def test_bias_count_equals_len_bias_flags(self):
        result = run_bias_detection(self._catalog_one(), **_T)
        assert result["bias_count"] == len(result["bias_flags"])

    def test_thresholds_in_output_match_inputs(self):
        result = run_bias_detection(
            self._catalog_one(),
            underserved_threshold=0.3,
            translation_coverage_min=15.0,
            language_gap_max=25.0,
        )
        t = result["thresholds"]
        assert t["underserved_division_pct"] == 30.0
        assert t["translation_coverage_min_pct"] == 15.0
        assert t["language_gap_max_pct"] == 25.0


# ══════════════════════════════════════════════════════════════════════════════
# Division slice
# ══════════════════════════════════════════════════════════════════════════════


class TestDivisionSlice:
    def test_single_division_form_count(self):
        catalog = [
            _form("F001", appearances=[_app("Civil")]),
            _form("F002", appearances=[_app("Civil")]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert data["Civil"]["total_forms"] == 2

    def test_multiple_divisions(self):
        catalog = [
            _form("F001", appearances=[_app("Civil")]),
            _form("F002", appearances=[_app("Criminal")]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert "Civil" in data
        assert "Criminal" in data

    def test_form_in_multiple_divisions_counted_in_each(self):
        catalog = [
            _form("F001", appearances=[_app("Civil"), _app("Housing")]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert data["Civil"]["total_forms"] == 1
        assert data["Housing"]["total_forms"] == 1

    def test_forms_with_no_appearances_not_counted(self):
        catalog = [_form("F001", appearances=[])]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert len(data) == 0

    def test_es_coverage_pct_calculated_correctly(self):
        catalog = [
            _form("F001", appearances=[_app("Civil")], versions=[_version(es="/es/form.pdf")]),
            _form("F002", appearances=[_app("Civil")], versions=[_version()]),  # no ES
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        # 1 of 2 form-appearances has ES → 50%
        assert data["Civil"]["es_coverage_pct"] == 50.0

    def test_pt_coverage_pct_calculated_correctly(self):
        catalog = [
            _form("F001", appearances=[_app("Civil")], versions=[_version(pt="/pt/form.pdf")]),
            _form("F002", appearances=[_app("Civil")], versions=[_version()]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert data["Civil"]["pt_coverage_pct"] == 50.0

    def test_no_versions_zero_coverage(self):
        catalog = [_form("F001", appearances=[_app("Civil")], versions=[])]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_division"]["data"]
        assert data["Civil"]["es_coverage_pct"] == 0
        assert data["Civil"]["pt_coverage_pct"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Underserved division flag
# ══════════════════════════════════════════════════════════════════════════════


class TestUnderservedDivisionFlag:
    def test_no_flag_when_counts_balanced(self):
        catalog = [
            _form("F001", appearances=[_app("A")]),
            _form("F002", appearances=[_app("B")]),
        ]
        result = run_bias_detection(catalog, underserved_threshold=0.5, translation_coverage_min=0.0, language_gap_max=100.0)
        types = [f["type"] for f in result["bias_flags"]]
        assert "underserved_division" not in types

    def test_flag_when_division_far_below_mean(self):
        # A=10, B=10, C=1 → mean=7, C < 7*0.5=3.5 → flagged
        catalog = (
            [_form(f"A{i}", appearances=[_app("DivA")]) for i in range(10)]
            + [_form(f"B{i}", appearances=[_app("DivB")]) for i in range(10)]
            + [_form("C1", appearances=[_app("DivC")])]
        )
        result = run_bias_detection(catalog, underserved_threshold=0.5, translation_coverage_min=0.0, language_gap_max=100.0)
        underserved = [f for f in result["bias_flags"] if f["type"] == "underserved_division"]
        assert any(f["slice"] == "DivC" for f in underserved)

    def test_underserved_flag_is_warning_severity(self):
        catalog = (
            [_form(f"A{i}", appearances=[_app("BigDiv")]) for i in range(20)]
            + [_form("S1", appearances=[_app("SmallDiv")])]
        )
        result = run_bias_detection(catalog, underserved_threshold=0.5, translation_coverage_min=0.0, language_gap_max=100.0)
        flags = [f for f in result["bias_flags"] if f["type"] == "underserved_division"]
        assert all(f["severity"] == "WARNING" for f in flags)


# ══════════════════════════════════════════════════════════════════════════════
# Low translation coverage flag
# ══════════════════════════════════════════════════════════════════════════════


class TestLowTranslationCoverage:
    def test_no_es_translation_triggers_flag(self):
        catalog = [_form("F001", appearances=[_app("Civil")], versions=[_version()])]
        result = run_bias_detection(
            catalog,
            underserved_threshold=0.0,
            translation_coverage_min=20.0,
            language_gap_max=100.0,
        )
        low_trans = [f for f in result["bias_flags"] if f["type"] == "low_translation_coverage"]
        es_flags = [f for f in low_trans if "Spanish" in f["slice"]]
        assert len(es_flags) >= 1

    def test_no_pt_translation_triggers_flag(self):
        catalog = [_form("F001", appearances=[_app("Civil")], versions=[_version()])]
        result = run_bias_detection(
            catalog,
            underserved_threshold=0.0,
            translation_coverage_min=20.0,
            language_gap_max=100.0,
        )
        low_trans = [f for f in result["bias_flags"] if f["type"] == "low_translation_coverage"]
        pt_flags = [f for f in low_trans if "Portuguese" in f["slice"]]
        assert len(pt_flags) >= 1

    def test_full_translation_no_coverage_flag(self):
        catalog = [
            _form("F001", appearances=[_app("Civil")], versions=[_version(es="/es.pdf", pt="/pt.pdf")]),
        ]
        result = run_bias_detection(
            catalog,
            underserved_threshold=0.0,
            translation_coverage_min=20.0,
            language_gap_max=100.0,
        )
        low_trans = [f for f in result["bias_flags"] if f["type"] == "low_translation_coverage"]
        assert len(low_trans) == 0

    def test_low_coverage_flag_is_warning_severity(self):
        catalog = [_form("F001", appearances=[_app("Civil")], versions=[_version()])]
        result = run_bias_detection(
            catalog,
            underserved_threshold=0.0,
            translation_coverage_min=20.0,
            language_gap_max=100.0,
        )
        flags = [f for f in result["bias_flags"] if f["type"] == "low_translation_coverage"]
        assert all(f["severity"] == "WARNING" for f in flags)


# ══════════════════════════════════════════════════════════════════════════════
# Language coverage gap flag
# ══════════════════════════════════════════════════════════════════════════════


class TestLanguageCoverageGap:
    def _catalog_with_coverage(self, total: int, es_count: int, pt_count: int) -> list:
        forms = []
        for i in range(total):
            es = "/es.pdf" if i < es_count else None
            pt = "/pt.pdf" if i < pt_count else None
            forms.append(_form(f"F{i:03d}", versions=[_version(es=es, pt=pt)]))
        return forms

    def test_no_gap_within_threshold_no_flag(self):
        # ES=50%, PT=40% → gap=10% < 30%
        catalog = self._catalog_with_coverage(10, es_count=5, pt_count=4)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert len(gap_flags) == 0

    def test_gap_above_threshold_flagged(self):
        # ES=80%, PT=10% → gap=70% > 30%
        catalog = self._catalog_with_coverage(10, es_count=8, pt_count=1)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert len(gap_flags) == 1

    def test_es_higher_identifies_spanish_as_higher(self):
        catalog = self._catalog_with_coverage(10, es_count=8, pt_count=1)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert "Spanish" in gap_flags[0]["slice"]

    def test_pt_higher_identifies_portuguese_as_higher(self):
        catalog = self._catalog_with_coverage(10, es_count=1, pt_count=8)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert "Portuguese" in gap_flags[0]["slice"]

    def test_equal_coverage_no_gap_flag(self):
        catalog = self._catalog_with_coverage(10, es_count=5, pt_count=5)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert len(gap_flags) == 0

    def test_gap_flag_is_warning_severity(self):
        catalog = self._catalog_with_coverage(10, es_count=9, pt_count=0)
        result = run_bias_detection(catalog, underserved_threshold=0.0, translation_coverage_min=0.0, language_gap_max=30.0)
        gap_flags = [f for f in result["bias_flags"] if f["type"] == "language_coverage_gap"]
        assert gap_flags[0]["severity"] == "WARNING"


# ══════════════════════════════════════════════════════════════════════════════
# Section heading slice
# ══════════════════════════════════════════════════════════════════════════════


class TestSectionHeadingSlice:
    def test_single_section_counted(self):
        catalog = [_form("F001", appearances=[_app(section="Housing")])]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_section_heading"]["data"]
        assert "Housing" in data
        assert data["Housing"]["total_forms"] == 1

    def test_multiple_sections(self):
        catalog = [
            _form("F001", appearances=[_app(section="Housing")]),
            _form("F002", appearances=[_app(section="Family")]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_section_heading"]["data"]
        assert "Housing" in data
        assert "Family" in data

    def test_section_es_pt_coverage_pct(self):
        catalog = [
            _form("F001", appearances=[_app(section="Housing")], versions=[_version(es="/es.pdf")]),
            _form("F002", appearances=[_app(section="Housing")], versions=[_version()]),
        ]
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_section_heading"]["data"]
        assert data["Housing"]["es_coverage_pct"] == 50.0
        assert data["Housing"]["pt_coverage_pct"] == 0.0

    def test_unknown_section_used_when_missing(self):
        catalog = [_form("F001", appearances=[{"division": "Civil"}])]  # no section_heading key
        result = run_bias_detection(catalog, **_T)
        data = result["slices"]["by_section_heading"]["data"]
        assert "Unknown" in data

    def test_section_stats_present(self):
        catalog = [_form("F001", appearances=[_app(section="Civil")])]
        result = run_bias_detection(catalog, **_T)
        assert "stats" in result["slices"]["by_section_heading"]


# ══════════════════════════════════════════════════════════════════════════════
# Version stats
# ══════════════════════════════════════════════════════════════════════════════


class TestVersionStats:
    def test_multi_version_forms_count(self):
        catalog = [
            _form("F001", current_version=1),
            _form("F002", current_version=3),
            _form("F003", current_version=2),
        ]
        result = run_bias_detection(catalog, **_T)
        by_ver = result["slices"]["by_version"]
        # F002 (v3) and F003 (v2) have current_version > 1
        assert by_ver["multi_version_forms"] == 2

    def test_all_single_version_zero_multi(self):
        catalog = [_form("F001", current_version=1), _form("F002", current_version=1)]
        result = run_bias_detection(catalog, **_T)
        assert result["slices"]["by_version"]["multi_version_forms"] == 0

    def test_version_stats_keys_present(self):
        catalog = [_form("F001", current_version=1)]
        result = run_bias_detection(catalog, **_T)
        stats = result["slices"]["by_version"]["stats"]
        assert "count" in stats
        assert "mean" in stats
        assert "std_dev" in stats


# ══════════════════════════════════════════════════════════════════════════════
# Language overall coverage slice
# ══════════════════════════════════════════════════════════════════════════════


class TestLanguageOverallCoverage:
    def test_no_translations_zero_pct(self):
        catalog = [_form("F001", versions=[_version()])]
        result = run_bias_detection(catalog, **_T)
        lang = result["slices"]["by_language"]["data"]
        assert lang["Spanish"]["coverage_pct"] == 0.0
        assert lang["Portuguese"]["coverage_pct"] == 0.0

    def test_full_translations_100_pct(self):
        catalog = [
            _form("F001", versions=[_version(es="/es.pdf", pt="/pt.pdf")]),
            _form("F002", versions=[_version(es="/es2.pdf", pt="/pt2.pdf")]),
        ]
        result = run_bias_detection(catalog, **_T)
        lang = result["slices"]["by_language"]["data"]
        assert lang["Spanish"]["coverage_pct"] == 100.0
        assert lang["Portuguese"]["coverage_pct"] == 100.0

    def test_partial_coverage_pct_rounded(self):
        # 1 of 3 forms has ES → 33.3%
        catalog = [
            _form("F001", versions=[_version(es="/es.pdf")]),
            _form("F002", versions=[_version()]),
            _form("F003", versions=[_version()]),
        ]
        result = run_bias_detection(catalog, **_T)
        es_pct = result["slices"]["by_language"]["data"]["Spanish"]["coverage_pct"]
        assert es_pct == round(1 / 3 * 100, 1)

    def test_form_with_no_versions_not_counted_as_translated(self):
        catalog = [_form("F001", versions=[])]
        result = run_bias_detection(catalog, **_T)
        lang = result["slices"]["by_language"]["data"]
        assert lang["Spanish"]["total_forms"] == 0
        assert lang["Portuguese"]["total_forms"] == 0
