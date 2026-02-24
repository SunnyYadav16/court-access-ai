import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dags"))

import src.bias_detection as bd

# ══════════════════════════════════════════════════════════════════════════════
# Stats computation
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeStats:
    def test_compute_stats_empty(self):
        stats = bd._compute_stats([])
        assert stats["count"] == 0
        assert stats["mean"] == 0

    def test_compute_stats_values(self):
        stats = bd._compute_stats([10, 20, 30, 40, 50])
        assert stats["count"] == 5
        assert stats["mean"] == 30.0
        assert stats["median"] == 30.0
        assert stats["min"] == 10
        assert stats["max"] == 50
        assert stats["std_dev"] > 0

    def test_compute_stats_even_values(self):
        stats = bd._compute_stats([10, 20, 30, 40])
        assert stats["median"] == 25.0


# ══════════════════════════════════════════════════════════════════════════════
# run_bias_detection
# ══════════════════════════════════════════════════════════════════════════════


class TestRunBiasDetection:
    def test_empty_catalog(self):
        report = bd.run_bias_detection([])
        assert report["total_active"] == 0

    def test_ignores_archived_forms(self):
        catalog = [{"status": "archived", "form_id": "f1"}]
        report = bd.run_bias_detection(catalog)
        assert report.get("total_active_forms", report.get("total_active", 0)) == 0

    def test_computes_division_bias(self):
        # We need a mean of forms per division to test UNDERSERVED_THRESHOLD (0.5)
        # Div1: 10 forms
        # Div2: 2 forms (underserved)
        catalog = []
        for i in range(10):
            catalog.append(
                {
                    "status": "active",
                    "form_id": f"d1_{i}",
                    "appearances": [{"division": "Div1"}],
                    "versions": [{"file_path_original": "f.pdf"}],
                }
            )
        for i in range(2):
            catalog.append(
                {
                    "status": "active",
                    "form_id": f"d2_{i}",
                    "appearances": [{"division": "Div2"}],
                    "versions": [{"file_path_original": "f.pdf"}],
                }
            )

        report = bd.run_bias_detection(catalog)

        # Verify slice data exists
        div_data = report["slices"]["by_division"]["data"]
        assert "Div1" in div_data
        assert div_data["Div1"]["total_forms"] == 10
        assert div_data["Div2"]["total_forms"] == 2

        # Check bias flags
        flags = report["bias_flags"]
        underserved = [f for f in flags if f["type"] == "underserved_division"]
        assert len(underserved) == 1
        assert underserved[0]["slice"] == "Div2"

    def test_detects_language_translation_coverage_per_division(self):
        # Div1: 10 forms, 1 ES translated (10% < 20% threshold)
        catalog = []
        for i in range(10):
            catalog.append(
                {
                    "status": "active",
                    "form_id": f"d1_{i}",
                    "appearances": [{"division": "Div1"}],
                    "versions": [{"file_path_original": "f.pdf", "file_path_es": "es.pdf" if i == 0 else None}],
                }
            )

        report = bd.run_bias_detection(catalog)

        flags = report["bias_flags"]
        low_coverage = [f for f in flags if f["type"] == "low_translation_coverage" and "Spanish" in f["slice"]]
        assert len(low_coverage) == 1
        assert low_coverage[0]["value"] == 10.0  # 1 out of 10

    def test_detects_language_coverage_gap(self):
        # 10 forms
        # ES translates 8 (80%)
        # PT translates 1 (10%)
        # Gap > 30%
        catalog = []
        for i in range(10):
            catalog.append(
                {
                    "status": "active",
                    "form_id": f"f_{i}",
                    "versions": [
                        {
                            "file_path_original": "f.pdf",
                            "file_path_es": "es.pdf" if i < 8 else None,
                            "file_path_pt": "pt.pdf" if i < 1 else None,
                        }
                    ],
                }
            )

        report = bd.run_bias_detection(catalog)

        flags = report["bias_flags"]
        gap_flags = [f for f in flags if f["type"] == "language_coverage_gap"]
        assert len(gap_flags) == 1
        assert gap_flags[0]["value"] == 70.0  # 80 - 10
