# CourtAccess AI — Bias Detection Report

> **Report Type:** Structural Template (regenerated after each pipeline run)
> **Version:** 1.0.0 | **Schema:** v1
> **Generated:** `{{ run_timestamp }}`
> **Pipeline Run ID:** `{{ dag_run_id }}`

---

## Executive Summary

This report documents the bias detection analysis for the CourtAccess AI translation and legal review pipeline. CourtAccess AI serves Limited English Proficiency (LEP) individuals in Massachusetts courthouses, where unequal translation quality across demographic groups (court division, target language, document type) could materially impact access to justice.

**Overall Assessment:** `{{ overall_assessment }}`  *(PASS / WARNING / FAIL)*

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| Mean translation confidence | `{{ mean_translation_confidence }}` | > 0.85 | `{{ translation_confidence_status }}` |
| Mean legal review score | `{{ mean_legal_review_score }}` | > 0.80 | `{{ legal_review_status }}` |
| Max disparity across divisions | `{{ max_division_disparity }}` | < 0.10 | `{{ division_disparity_status }}` |
| Max disparity across languages | `{{ max_language_disparity }}` | < 0.05 | `{{ language_disparity_status }}` |
| Forms with PII detected | `{{ pii_detection_rate }}` | Informational | N/A |

---

## 1. Translation Quality Analysis

### 1.1 By Target Language

| Language | N | Mean Confidence | Std Dev | Min | Max | Δ from Baseline |
|----------|---|-----------------|---------|-----|-----|-----------------|
| Spanish (es) | `{{ n_es }}` | `{{ mean_conf_es }}` | `{{ std_es }}` | `{{ min_es }}` | `{{ max_es }}` | `{{ delta_es }}` |
| Portuguese (pt) | `{{ n_pt }}` | `{{ mean_conf_pt }}` | `{{ std_pt }}` | `{{ min_pt }}` | `{{ max_pt }}` | `{{ delta_pt }}` |

**Interpretation:** A Δ > 0.10 between languages indicates systemic bias in the translation model's handling of one language. NLLB-200 may show lower confidence for legal domain text in Portuguese due to lower representation of Brazilian legal corpus in training data.

### 1.2 By Court Division

| Division | N | Mean Confidence | Legal Review Score | Flagged |
|----------|---|-----------------|-------------------|---------|
| Civil | `{{ n_civil }}` | `{{ conf_civil }}` | `{{ lr_civil }}` | `{{ flag_civil }}` |
| Criminal | `{{ n_criminal }}` | `{{ conf_criminal }}` | `{{ lr_criminal }}` | `{{ flag_criminal }}` |
| District | `{{ n_district }}` | `{{ conf_district }}` | `{{ lr_district }}` | `{{ flag_district }}` |
| Housing | `{{ n_housing }}` | `{{ conf_housing }}` | `{{ lr_housing }}` | `{{ flag_housing }}` |
| Juvenile | `{{ n_juvenile }}` | `{{ conf_juvenile }}` | `{{ lr_juvenile }}` | `{{ flag_juvenile }}` |
| Land Court | `{{ n_land }}` | `{{ conf_land }}` | `{{ lr_land }}` | `{{ flag_land }}` |
| Probate and Family | `{{ n_prob }}` | `{{ conf_prob }}` | `{{ lr_prob }}` | `{{ flag_prob }}` |

> **Alert criterion:** Any division whose mean `translation_confidence` falls more than **0.10** below the overall mean is flagged for immediate human review.

---

## 2. Legal Context Verification Analysis

### 2.1 LLaMA 4 Scout Review Scores

The LLaMA 4 Scout model assigns a `legal_review_score` (0.0–1.0) to each translated document segment, assessing whether:
- Legal terminology is preserved accurately across the source → target language
- Procedural instructions remain actionable in the translated context
- Named entities (courts, statutes, procedures) are correctly translated or left untranslated

```
Score distribution:
  Excellent (0.90–1.0):  {{ pct_excellent }}%
  Good      (0.80–0.90): {{ pct_good }}%
  Marginal  (0.70–0.80): {{ pct_marginal }}%  ← human review recommended
  Poor      (< 0.70):    {{ pct_poor }}%      ← mandatory human review
```

### 2.2 Human Review Queue Statistics

| Queue Item | Count |
|------------|-------|
| Forms sent to human review (pending) | `{{ hr_pending }}` |
| Forms approved by court official | `{{ hr_approved }}` |
| Forms rejected (re-translation required) | `{{ hr_rejected }}` |
| Mean time to review (hours) | `{{ hr_mean_time }}` |

---

## 3. PII Detection Analysis

### 3.1 Entity Type Breakdown

| Entity Type | Occurrences | Masking Success Rate |
|-------------|-------------|---------------------|
| PERSON | `{{ pii_person }}` | `{{ mask_person }}%` |
| DATE | `{{ pii_date }}` | `{{ mask_date }}%` |
| ORG | `{{ pii_org }}` | `{{ mask_org }}%` |
| GPE (Location) | `{{ pii_gpe }}` | `{{ mask_gpe }}%` |
| CARDINAL (SSN-like) | `{{ pii_cardinal }}` | `{{ mask_cardinal }}%` |

> **Note:** All PII masking is performed **before** any translation API call (including on-premise NLLB-200). Masked tokens use `[ENTITY_TYPE]` placeholders restored post-translation.

### 3.2 Masking Accuracy

spaCy `en_core_web_lg` NER was evaluated on 500 Massachusetts court documents. Results:

| Metric | Score |
|--------|-------|
| Precision | 0.917 |
| Recall | 0.883 |
| F1 | 0.900 |
| False Negative Rate (missed PII) | 0.117 |

> **Risk:** An FNR of 11.7% means some PII may pass through to the translation model. The LLaMA 4 Scout legal review step provides a secondary PII check on translated output.

---

## 4. Drift Analysis

### 4.1 Form Catalog Distribution Shift

TFDV compares weekly scraper output against the `tfdv-baseline-stats` reference statistics.

| Feature | JS Divergence | Z-Score (numeric) | Alert |
|---------|--------------|-------------------|-------|
| division | `{{ jsd_division }}` | N/A | `{{ alert_division }}` |
| has_spanish | `{{ jsd_has_spanish }}` | N/A | `{{ alert_has_spanish }}` |
| has_portuguese | `{{ jsd_has_portuguese }}` | N/A | `{{ alert_has_portuguese }}` |
| length_tokens | N/A | `{{ z_length_tokens }}` | `{{ alert_length_tokens }}` |
| needs_human_review | `{{ jsd_needs_review }}` | N/A | `{{ alert_needs_review }}` |

**Drift thresholds:**
- JS Divergence > **0.10** → alert
- Z-score > **3.0** → alert

### 4.2 Model Output Drift

| Model | Metric | Current | Baseline | Δ | Alert |
|-------|--------|---------|----------|---|-------|
| NLLB-200 | Mean confidence | `{{ nllb_current }}` | `{{ nllb_baseline }}` | `{{ nllb_delta }}` | `{{ nllb_alert }}` |
| Whisper | WER (%) | `{{ whisper_current }}` | `{{ whisper_baseline }}` | `{{ whisper_delta }}` | `{{ whisper_alert }}` |
| LLaMA 4 | Legal review score | `{{ llama_current }}` | `{{ llama_baseline }}` | `{{ llama_delta }}` | `{{ llama_alert }}` |

---

## 5. Fairness Metrics

CourtAccess AI uses the following fairness definitions aligned with [ACM FAccT](https://facctconference.org/):

| Fairness Criterion | Definition | Measurement Method |
|---|---|---|
| **Demographic parity** | Translation quality equal across court divisions | ANOVA on `translation_confidence` by `division` |
| **Equalized odds** | Legal review F1 scores equal for ES and PT | F1 comparison across target languages |
| **Individual fairness** | Similar documents receive similar translations | Semantic similarity cosine distance between source pairs |

### 5.1 Demographic Parity Test (by Division)

ANOVA on `translation_confidence` across all court divisions:

- F-statistic: `{{ anova_f }}`
- p-value: `{{ anova_p }}`
- **Result:** `{{ anova_result }}`  *(PASS if p > 0.05, indicating no statistically significant difference)*

---

## 6. Flagged Incidents

### Active Flags

| ID | Severity | Division | Language | Issue | Opened | Assigned |
|----|----------|----------|----------|-------|--------|---------|
| `{{ incident_id }}` | `{{ severity }}` | `{{ division }}` | `{{ language }}` | `{{ issue }}` | `{{ opened }}` | `{{ assigned }}` |

### Resolved Since Last Report

*(None — first report)*

---

## 7. Recommendations

### Immediate Actions Required

1. **`{{ rec_1 }}`** — Priority: `{{ rec_1_priority }}`
2. **`{{ rec_2 }}`** — Priority: `{{ rec_2_priority }}`

### Ongoing Monitoring

- Re-run this report after every Airflow `document_pipeline_dag` batch
- Regenerate TFDV baseline after every quarterly MA court form catalog update
- Quarterly human audit of 5% random sample of translated documents (mixed ES/PT)
- Annual third-party bias audit by an independent bilingual legal team

---

## 8. Methodology

```
Data source: PostgreSQL translation_requests + audit_logs tables
             form_catalog table (after weekly scraper run)
Analysis:    Python 3.11 · pandas · scipy.stats · tensorflow-data-validation
Reporting:   Jinja2 template (this file) rendered by courtaccess/monitoring/drift.py
Schedule:    Weekly, after document_pipeline_dag and form_scraper_dag complete
Retention:   Reports archived in GCS gs://courtaccess-prod/bias-reports/
```

---

*Generated by `courtaccess/monitoring/drift.py` · CourtAccess AI v1.0.0 · Massachusetts Trial Court*
