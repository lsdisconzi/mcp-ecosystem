# Pipeline Check V22 — `candidate_verbatim_verification`

**Status:** New check (proposed 2026-09-17)
**Family:** Candidate integrity (extends V04, V06, V13)
**Severity:** `warn` on first occurrence; `fail` on regression
**Depends on:** V04 (article_exists_in_framework_cache), corpus cache registration

---

## Purpose

Prevent a candidate article from being **removed** (or **kept**) on the basis of its legacy label alone. A removal decision is only valid if it is grounded in the article's **verbatim text**.

This check closes a real gap that produced a real error during the CL-030 candidate review: the legacy labels for CPCL Arts. 193, 194, 195, 196, 197 did not match the articles' actual text. A review that consulted only the labels would have:
- Removed Arts. 193, 194, 196 (wrongly — the articles are applicable under their true text)
- Kept Art. 195 under a label with no relation to the article

The error only surfaced when the review consulted the verbatim text in `data/law/CL/CHIPENCOD_CP.md`.

---

## Rule statement

> **Before any candidate article is removed, re-labelled, or marked `not_applicable`, the pipeline must record:**
>
> 1. The **legacy label** as it appeared in the pre-review file.
> 2. The **verbatim text** of the article, sourced from a registered or corpus cache.
> 3. A **semantic comparison** between (1) and (2).
> 4. A **decision** (keep / correct / remove) that is grounded in (2), not (1).
>
> Removal based solely on the legacy label is **invalid** and must be reported.

---

## Check definition

```json
{
  "check_id": "V22",
  "name": "candidate_verbatim_verification",
  "family": "candidate_integrity",
  "severity": "warn",
  "inputs": [
    "violation.candidate_articles[]",
    "framework_caches[]",
    "corpus_caches[]  (indexed by article_id → verbatim_text)",
    "violation.provenance[]  (candidate review events)"
  ],
  "algorithm": [
    "For each candidate article C in violation.candidate_articles:",
    "  1. Locate the article's verbatim text via the corpus index. If not found, record status='verbatim_unavailable' and skip the semantic check (but emit a warn).",
    "  2. Extract the legacy label L from C.candidate_name and C.history_note ('legacy label' fragment).",
    "  3. Compute semantic similarity between L and verbatim text V:",
    "       - tokenize both",
    "       - compute Jaccard and normalized Levenshtein on the legal-noun head of each (e.g. 'falso testimonio' vs 'falsedad documental')",
    "       - compute weighted overlap of legal terms drawn from a curated term list (acción, denuncia, falsedad, prevaricación, cohecho, etc.)",
    "  4. If similarity < threshold (suggested 0.35 weighted):",
    "       status='label_text_mismatch'",
    "       and require the candidate's history_note to contain an explicit 'Corrected <date>: legacy label ... did not match the article' fragment.",
    "  5. If C.decision == 'remove' and step 4 did NOT detect a mismatch, PASS.",
    "  6. If C.decision == 'remove' and the removal was asserted in the candidate review but no verbatim text was consulted (i.e. no history_note references a verbatim source), emit FAIL.",
    "  7. If C.decision == 'correct' and history_note documents the label mismatch against a named verbatim source, PASS."
  ],
  "output_schema": {
    "check_id": "V22",
    "name": "candidate_verbatim_verification",
    "status": "pass | warn | fail",
    "details": "<string>",
    "per_candidate": [
      {
        "candidate_article_id": "<id>",
        "legacy_label": "<string>",
        "verbatim_source": "<file path or null>",
        "semantic_similarity": 0.00,
        "decision_recorded": "keep | correct | remove",
        "status": "ok | verbatim_unavailable | label_text_mismatch | unverified_removal"
      }
    ]
  }
}
```

---

## Pass / warn / fail semantics

| Outcome | Condition |
|---|---|
| **pass** | Every candidate: verbatim text available; decisions grounded in it; no unverified removal. |
| **warn** | One or more candidates have verbatim text unavailable, **but** no removal decision was made on those candidates. The pipeline flags them for future review. |
| **fail** | At least one candidate was **removed** on the basis of a legacy label without consulting verbatim text. |

---

## Example outputs

### Example 1 — PASS (as observed post-CL-030 backend update)

```json
{
  "check_id": "V22",
  "name": "candidate_verbatim_verification",
  "status": "pass",
  "details": "10 candidate(s) checked; 10 verbatim source(s) resolved; 0 unverified removal(s); 5 label_text_mismatch(es) correctly reclassified.",
  "per_candidate": [
    {
      "candidate_article_id": "CL.CPCL.C1.Art.269_ter",
      "legacy_label": "Obstrucción a la investigación por ocultamiento, alteración o destrucción de antecedentes",
      "verbatim_source": "Legal framework/CodigoPenal_269bis_269ter.md",
      "semantic_similarity": 0.94,
      "decision_recorded": "keep",
      "status": "ok"
    },
    {
      "candidate_article_id": "CL.CPCL.Art.193",
      "legacy_label": "Falso testimonio o acusación falsa por funcionario público",
      "verbatim_source": "data/law/CL/CHIPENCOD_CP.md",
      "semantic_similarity": 0.12,
      "decision_recorded": "correct",
      "status": "label_text_mismatch"
    }
  ]
}
```

### Example 2 — FAIL (would have triggered on my initial label-driven review)

```json
{
  "check_id": "V22",
  "name": "candidate_verbatim_verification",
  "status": "fail",
  "details": "1 candidate(s) removed without verbatim verification: CL.CPCL.Art.193 (removal asserted on legacy label 'Falso testimonio o acusación falsa' without consulting the article's text).",
  "per_candidate": [
    {
      "candidate_article_id": "CL.CPCL.Art.193",
      "legacy_label": "Falso testimonio o acusación falsa por funcionario público",
      "verbatim_source": null,
      "semantic_similarity": null,
      "decision_recorded": "remove",
      "status": "unverified_removal"
    }
  ]
}
```

---

## Regression test cases

| # | Input | Expected |
|---|---|---|
| 1 | CL-030 (post-backend) candidate list | **pass** — 5 label_text_mismatch reclassified |
| 2 | CL-030 (my first draft) candidate list | **fail** — Art. 193, 194, 196 removed on legacy label |
| 3 | A hypothetical candidate whose legacy label matches its verbatim text and is removed with a verbatim source cited | **pass** |
| 4 | A candidate whose verbatim text cannot be located and is not removed | **warn** |
| 5 | A candidate whose verbatim text cannot be located and **is** removed | **fail** |

---

## Interaction with existing checks

| Check | Relationship |
|---|---|
| **V04** `article_exists_in_framework_cache` | V22 extends V04: V04 confirms the article exists in a registered cache; V22 confirms **which text** was consulted and **how** it was compared to the label. |
| **V06** `element_coverage` | V22 is a precondition: only candidates that pass V22 should have element grids built. |
| **V13** `evidence_nexus_coherence` | V22 and V13 are orthogonal: V22 checks *label-vs-text*; V13 checks *nexus-vs-grid*. Both must pass. |
| **V21** `element_id_closure` | V22 does not affect V21 (element_id hierarchy) — they address different concerns. |

---

## Rollout plan

1. **Dry-run** on CL-001, CL-002, CL-005, CL-030 candidate lists. Record V22 output but do not gate.
2. **Review** dry-run output against human candidate reviews.
3. **Enable `warn` mode** in the pipeline. Any label_text_mismatch not accompanied by a documented correction becomes a warn.
4. **Enable `fail` mode** after a 2-week observation window. Any unverified removal blocks the bundle.

---

## Curated legal-term list (for step 3 of the algorithm)

Suggest seeding the semantic term list with:

- delitos: `falsedad`, `prevaricación`, `cohecho`, `malversación`, `denuncia`, `querella`, `testimonio`, `calumnia`, `injuria`, `usurpación`, `nombramiento`, `obstrucción`, `encubrimiento`, `vejación`, `abuso`, `omisión`, `retardo`, `soborno`, `tráfico`, `influencia`
- actores: `empleado público`, `funcionario`, `particular`, `autoridad`, `juez`, `fiscal`, `abogado`, `perito`, `policía`
- instrumentos: `documento`, `instrumento`, `parte`, `providencia`, `resolución`, `informe`, `dictamen`

The list is intentionally narrow: it should be tuned over time as false positives/negatives appear.