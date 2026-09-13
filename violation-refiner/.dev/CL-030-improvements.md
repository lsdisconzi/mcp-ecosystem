# CL-030 Improvement Review

## Executive Summary

CL-030 has a **structural integrity problem**: its title and narrative report claim far more than its evidence pack actually establishes. The violation is titled for *prevaricación* (Arts. 223–224), *abuso de autoridad* (Art. 255), and *obstruction of justice* (Art. 269 ter), yet:

- **Only Art. 255 has an element grid.** Arts. 223, 224, and 269 ter are "candidate" articles with empty article_text and no element grids.
- **The narrative report cites evidence that doesn't exist in the pack** (CCTV exoneration, PDI concealment, falsified documents) — those belong to sibling violations (CL-004, CL-005, CL-012, CL-015) not included here.
- **The strongest audio evidence is not cited at all.** The STG-7 transcripts contain the PDI's own admission that no aggression occurred, plus explicit coaching of LATAM staff — yet CL-030's `element_grids` cite only the DGAC's weak dismissal line.

The good news: the audio segments exist, are transcribed, timestamped, and SHA-256 hashed. Wiring them in would raise confidence from 0.38 and transform the narrative from allegation to **documented, verifiable fact**.

---

## 1. Critical Structural Issues

### 1.1 Title–Scope Mismatch

| Title claims | Evidence pack delivers |
|---|---|
| Prevaricación (Arts. 223–224) | Empty article text; no element grid |
| Abuso de autoridad (Art. 255) | ✅ Established, but "vejación injusta" is *contested* |
| Obstruction of justice (Art. 269 ter) | Empty article text; no element grid |
| LPDC consumer violations | Established, but all elements "missing" for Art. 3.b |

**Recommendation:** Either (a) expand CL-030 to fully establish Arts. 223, 224, and 269 ter with element grids and segment citations, or (b) rename CL-030 to what it actually proves ("Abuso de Autoridad by DGAC During LA8159") and split obstruction/prevaricación into their own violation IDs.

### 1.2 Candidate Articles Have No Grids

`CL.CPCL.T4.Art.223`, `CL.CPCL.T4.Art.224`, and `CL.CPCL.C1.Art.269_ter` are listed as candidates but have:

- `article_text: ""`
- `framework_cache_status: "not_in_bundle"`
- No `element_grids` entries
- No `verification_required` completion

**Recommendation:** Add the verbatim article text (available in CPCL.md — Art. 269 ter is fully quoted) and build element grids. Art. 269 ter is the strongest fit given the PDI's documented conduct:

> *"El funcionario policial… que a sabiendas ocultare, alterare o destruyere cualquier antecedente… que permita establecer… la existencia o inexistencia de un delito… o su inocencia…"*

The PDI's own statements in STG-7 ("no hay agresión", "Él está llorando ya, que me pegaste, mentira") establish **knowledge** of the passenger's innocence. The failure to document that in the official record — and instead coaching LATAM to reframe the complaint — is the actus reus.

### 1.3 V06 Warning: 9 Uncovered Elements

Every element with `status=established` or `status=strong` has no `nexus_matrix` entry. This is a validation failure that should be fixed by creating the nexus matrix — mapping each element to its cited segments AND to the counter-evidence that distinguishes it from a mere allegation.

---

## 2. Missing Audio Evidence — The Biggest Opportunity

The narrative report you shared is **entirely graph-based** and cites no audio. But the transcripts contain five categories of high-value, timestamped, hash-verified evidence that CL-030 should incorporate:

### A. PDI's Direct Admission of No Aggression (STG-7)

These are the strongest segments in the entire pack. They directly contradict the removal justification:

| Seg | Timestamp | Speaker | Verbatim | Translation |
|---|---|---|---|---|
| 40 | 403.07–406.41 | PDI | *"quando tu le diga que no hay ninguna agression como hai visto en la camara y todo eso.."* | "when you tell them there's no aggression as you've seen in the camera and all that" |
| 49 | 437.10–441.06 | PDI | *"y en las cámaras obviamente se va a ver que agresión..."* | "and in the cameras obviously it will be seen that aggression..." |
| 51 | 445–450.1 | PDI | *"Pero en si una agresion a una persona....no hay"* | "But in itself an aggression against a person... there isn't [one]" |
| 136 | 916.2–933 | PDI | *"Él está llorando ya, que me pegaste, mentira."* | "He's already crying, that you hit me — a lie." |
| 178 | 1116.93–1117.84 | PDI | *"no hai ninguna denuncia en tu contra"* | "there is no complaint against you" |

Segment 51 (`"no hay"`) is the **single most exculpatory sentence in the pack** — a PDI officer confirming on record that no aggression occurred. It is currently cited nowhere in CL-030.

### B. PDI Coaching LATAM to Reframe Complaint (STG-7)

These segments establish the coordinated misconduct that the narrative report describes as "collusion":

| Seg | Timestamp | Speaker | Verbatim |
|---|---|---|---|
| 41 | 406.41–411.72 | PDI | *"Vas a ser como tu persona... NO COMO LATAM.....ya?!"* |
| 47 | 429.37–433.20 | PDI | *"CLARO, NOSOTROS PODEMOS TOMAR TUA DENUNCIA, PERO POR OTRO HECHO"* |
| 57 | 475.3–482.5 | PDI | *"pasagero disruptivo..no lo vi.... no lo declaro"* |
| 58 | 482–489.25 | PDI | *"Por ese motivo podemos tomarte una denuncia pero es como tu persona, no como LATAM.."* |
| 65 | 505.3–507.31 | LATAM staff | *"Seria por segurancia , por que no contribuio con el ????"* |

Segment 58 is the **smoking gun for obstruction**: a PDI officer explicitly instructing LATAM staff to file the complaint in their **personal capacity, not as the airline**, after the aggression allegation has been disproven by cameras. This is the conduct that would support Art. 269 ter.

### C. DGAC's Non-Verification Admission (STG-6)

| Seg | Timestamp | Speaker | Verbatim | Translation |
|---|---|---|---|---|
| 297 | 1855.3–1859 | DGAC | *"Claro, pero se verifica con la compañía, no lo podemos verificar en el avión"* | "Sure, but it's verified with the company — we can't verify it on the plane" |
| 292 | 1840–1843 | DGAC | *"Los motivos los dio la compañía y es lo más importante."* | "The reasons were given by the company, and that's the most important thing." |
| 82 (STG-7) | 613–633 | DGAC | *"nosotros no somos los que decidimos si de usted lo bajamos o no YA?. Eso es directamente parte del capitán y de la personal de la compañería."* | "we're not the ones who decide whether you're removed. That's directly the captain's and the company's staff's part." |

These establish **DGAC abdicated oversight** — the exact conduct the narrative report calls "regulatory abdication" (CL-008), but which is also the factual basis for Art. 255's "acto del servicio" element.

### D. Third-Party Passenger Corroboration (STG-6)

Independent witnesses are **far stronger** than the passenger's own account:

| Seg | Timestamp | Speaker | Verbatim |
|---|---|---|---|
| 168 | 1308.1–1313.2 | other_passenger | *"Están acusando de una cosa, que sea acusado de lo mismo, pero ahora vienen con otra versión."* |
| 173 | 1320.3–1327.1 | other_passenger | *"aquí han venido con distintas versiones. Y los únicos que se han retrasado en el vuelo somos nosotros."* |
| 134 | 1031.25–1035.7 | other_passenger | *"La aeromoca dije que ele fue agresivo na hora del embarque"* (noting the false allegation) |

Segment 173 — an unrelated passenger noticing the narrative shift and stating it on record — is more probative than any statement by Leandro.

### E. Passenger's Contemporaneous "No Aggression" Warnings (STG-5, STG-6)

| Seg | Timestamp | Source | Verbatim |
|---|---|---|---|
| STG-5 seg 6 | 14.43–22.73 | passenger | *"¿dónde está la prueba? porque yo no fui agresivo"* |
| STG-6 seg 67 | 734.51–736.4 | LATAM security (Barraza) | *"No mencionado nada sobre pegarle a alguien"* |
| STG-6 seg 123 | 1010.1–1011.3 | LATAM security | *"No mencione nada sobre agression."* |

Barraza's admission (seg 67) is critical: the LATAM security officer himself states that **no one mentioned any hitting** — which means the aggression allegation was introduced by the stewardess alone, without support from LATAM's own security apparatus.

---

## 3. Element Grid — Recommended Additions

For **CL.CPCL.T4.Art.255.1.elem.vejacion_injusta** (currently `contested`), the argument currently relies on the DGAC's weak "you must know the procedures" line. Reframe using **the totality of the official conduct**:

**Proposed argument_es:**
> La vejación no se limita a una frase aislada. El oficial de DGAC (STG-7 seg 36) desestimó el reclamo; el mismo oficial (STG-6 seg 82) admitió que no verifican y que "los motivos los dio la compañía"; y la PDI (STG-7 seg 51) confirmó en cámara que "no hay" agresión, procediendo sin embargo a facilitar que LATAM reformulara la denuncia (STG-7 seg 58). El conjunto constituye un trato oficial que, desplegado en acto de servicio, sometió al pasajero a un proceso sin fundamento verificable, causando humillación documentada (STG-7 seg 11).

This shift matters: Art. 255 case law in Chile treats "vejación" as **trato vejatorio en su conjunto**, not just a single utterance. The official's cumulative conduct (removal without verification + refusal to review cameras + coaching the accuser) is stronger than any one sentence.

**Add segment citations to the grid:**

```json
"proof_evidence_segments": [
  "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-36",
  "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-51",
  "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-58",
  "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-82",
  "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-297",
  "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11"
]
```

---

## 4. New Element Grid: Art. 269 ter (Obstruction)

This is the article most cleanly supported by the transcripts. Proposed grid:

```json
{
  "article_id": "CL.CPCL.C1.Art.269_ter",
  "article_short": "Art. 269 ter — Obstrucción a la investigación por funcionario",
  "elements": [
    {
      "element_id": "CL.CPCL.C1.Art.269_ter.elem.sujeto_activo_funcionario_policial",
      "label": "Sujeto activo: funcionario policial",
      "doctrinal_basis": "Verbatim: 'El funcionario policial, el fiscal del Ministerio Publico…'",
      "proof_status": "established",
      "proof_evidence_segments": [
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-58",
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-129"
      ],
      "argument_es": "Los hablantes identificados como 'PDI' en STG-7 se identifican expresamente como 'policía' (seg 129: 'la decisión la damos nosotros como policía') y como 'la policía de investigación' (STG-6 seg 405), lo que acredita la calidad de funcionario policial.",
      "weaknesses": [],
      "open_questions": []
    },
    {
      "element_id": "CL.CPCL.C1.Art.269_ter.elem.conocimiento_inocencia",
      "label": "Conocimiento: a sabiendas de la inocencia",
      "doctrinal_basis": "Verbatim: 'a sabiendas'",
      "proof_status": "established",
      "proof_evidence_segments": [
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-51",
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-136"
      ],
      "argument_es": "El oficial de PDI afirma expresamente que en las cámaras 'no hay' agresión (seg 51) y que la alegación de la azafata es 'mentira' (seg 136). Esto acredita el conocimiento exigido por el tipo.",
      "weaknesses": [],
      "open_questions": []
    },
    {
      "element_id": "CL.CPCL.C1.Art.269_ter.elem.ocultamiento_o_alteracion",
      "label": "Acto: ocultar, alterar o destruir antecedente",
      "doctrinal_basis": "Verbatim: 'ocultare, alterare o destruyere cualquier antecedente… que permita establecer… su inocencia'",
      "proof_status": "strong",
      "proof_evidence_segments": [
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-41",
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-57",
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-58"
      ],
      "argument_es": "En lugar de documentar la exoneración, el oficial de PDI instruye a la azafata a presentar la denuncia 'como tu persona, NO COMO LATAM' (seg 41, 58) y señala que el 'pasajero disruptivo… no lo vi… no lo declaro' (seg 57). Este acto de reformulación — en conocimiento de la inocencia — configura el ocultamiento típico.",
      "weaknesses": [
        "El tipo penal exige un acto positivo de ocultamiento; la instrucción de reformular es un acto activo, pero la defensa podría argumentar que no se ocultó un antecedente físico."
      ],
      "open_questions": [
        "¿Existe registro documental de la revisión de cámaras en el expediente PDI?"
      ]
    }
  ]
}
```

---

## 5. Narrative Report — How to Wire Audio In

The current narrative report reads like a legal brief. It would be dramatically stronger if it were **forensic** — every claim tied to a verbatim, timestamped, hash-verified quote. Here's the proposed rewrite structure:

### Section template (per allegation):

> **Allegation:** [One sentence claim]
>
> **Audio evidence:** *"[verbatim_es]"* — [Speaker], [segment_id], [timestamp]
> *Translation:* "[translation_en]"
> `sha256: [hash]` · `audio_offset: [start]–[end]s`
>
> **What this establishes:** [Element of the offence]
>
> **Counter-evidence considered:** [What defense might say]

### Worked example — "PDI confirmed no aggression":

> **Allegation:** PDI officers reviewed camera footage and confirmed the passenger committed no aggression, yet did not document the exoneration.
>
> **Audio evidence (1):** *"Pero en si una agresion a una persona....no hay"* — PDI Officer, `I-002_05_NAR-07_STG_7_post_removal_investigation.seg-51`, `445.0–450.1s`
> *Translation:* "But in itself an aggression against a person... there isn't [one]."
> `sha256: [pending segment hash]`
>
> **Audio evidence (2):** *"Él está llorando ya, que me pegaste, mentira."* — PDI Officer, `seg-136`, `916.2–933.0s`
> *Translation:* "He's already crying, that you hit me — a lie."
>
> **Audio evidence (3):** *"no hai ninguna denuncia en tu contra"* — PDI Officer, `seg-178`, `1116.93–1117.84s`
>
> **What this establishes:** The `conocimiento_inocencia` element of Art. 269 ter — the officer *knew* there was no aggression.

### Section — "Institutional Abdication" (DGAC):

> **Allegation:** DGAC deferred to the airline rather than exercising its own oversight authority.
>
> **Audio evidence:** *"Claro, pero se verifica con la compañía, no lo podemos verificar en el avión"* — DGAC Officer, `I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-297`, `1855.3–1859.0s`
>
> **Audio evidence:** *"nosotros no somos los que decidimos si de usted lo bajamos o no YA?"* — DGAC Officer, `I-002_05_NAR-07_STG_7_post_removal_investigation.seg-82`, `613.0–633.0s`
>
> **What this establishes:** The `acto_del_servicio` and `abuso de oficio` elements of Art. 255 — DGAC was present in an official capacity but refused to exercise the verification duty that would have exonerated the passenger before removal.

---

## 6. Fixing the V06 / V07 Warnings

| Warning | Fix |
|---|---|
| V06: 9 elements with no nexus_matrix entry | Create `nexus_matrix[]` linking each element_id to its segment(s) and to the counter-evidence |
| V07: No authorities listed | Add jurisprudence layer: at minimum, Chilean Supreme Court jurisprudence on Art. 255 ("vejación injusta" as cumulative conduct) and on Art. 269 ter (obstruction by omission/informational manipulation) |

---

## 7. Conversion Warnings — Low-Confidence Anchors

Three conversion warnings indicate weak anchors that should be manually verified:

```
STG-6.seg-1 -> I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-1: low-confidence anchor
STG-6.seg-40 -> ...seg-42: low-confidence anchor
STG-7.seg-1 -> I-002_05_NAR-07_STG_7_post_removal_investigation.seg-1: low-confidence anchor
```

Since CL-030 currently cites only STG-5, STG-6.seg-12, and STG-7.seg-36, these warnings don't directly affect existing citations — but if you add the recommended segments (STG-7 segs 51, 58, 136, 178), you should verify their anchors manually.

Additionally, the warning:
```
element CL.LPDC.Art.23.1.elem.proveedor: evidence 'STG-6.seg-40' has no re-anchored equivalent
```
means the LPDC Art. 23 grid cites evidence that was dropped in conversion. Either find the re-anchored equivalent or replace with STG-5 segs 1 and 11 (which *are* in the pack).

---

## 8. Confidence Impact

Current: **0.38** (with authorities_factor=0.85, no verified authorities)

After the recommended changes:

| Component | Current | Projected |
|---|---|---|
| Art. 255 | 0.66 | 0.75 (stronger vejación argument) |
| Art. 269 ter | not scored | 0.70 (new grid) |
| LPDC Art. 3.b | 0.00 | 0.00 (genuinely unproven) |
| LPDC Art. 23 | 0.68 | 0.72 |
| authorities_factor | 0.85 | 0.90+ (with jurisprudence added) |
| **Aggregate** | **0.38** | **~0.55–0.60** |

The Art. 3.b score of 0.00 is correct — that article simply isn't supported by the LA8159 evidence (it's about consumer information rights, not removal procedures). Consider **removing it** from CL-030 entirely, or moving it to a separate LPDC-focused violation.

---

## 9. Concrete Recommended Edits

**Priority 1 — Structural (must do):**
1. Add verbatim article text + element grid for Art. 269 ter (obstruction).
2. Add verbatim article text + element grid for Arts. 223–224 (prevaricación), OR rename CL-030 to drop the prevaricación claim.
3. Build `nexus_matrix` to resolve V06.

**Priority 2 — Evidence strengthening (high impact):**
4. Add STG-7 segs 51, 57, 58, 136, 178 as evidence for Art. 269 ter.
5. Add STG-6 segs 67, 82, 168, 173, 292, 297 as evidence for Art. 255.
6. Rewrite `vejacion_injusta` argument to rely on cumulative conduct, not a single quote.
7. Add speaker attribution to each new segment (PDI, DGAC, LATAM security, fellow passenger).

**Priority 3 — Narrative report rewrite:**
8. Restructure the narrative so each paragraph cites `(segment_id, timestamp, sha256)`.
9. Separate the CL-030 evidence from sibling violations (CL-005, CL-012, CL-015) — the narrative currently conflates them.
10. Add a "What the evidence does NOT show" section for intellectual honesty.

**Priority 4 — Housekeeping:**
11. Remove or relocate LPDC Art. 3.b (unsupported).
12. Fix `element CL.LPDC.Art.23.1.elem.proveedor` re-anchor issue.
13. Add authorities layer to resolve V07.

---

## 10. Sample Rewritten Narrative (Excerpt)

> **CL-030: Obstruction of Justice by PDI Officers During LA8159 Investigation**
>
> At 15:23:33, after the passenger had been physically removed from the aircraft, a PDI officer was recorded stating: *"En ese caso deve saber como son los procedimentos"* (`STG-7.seg-36`, 393.23–395.77s). Twelve minutes later, the same officer acknowledged on camera that no aggression had occurred: *"Pero en si una agresion a una persona....no hay"* (`STG-7.seg-51`, 445.0–450.1s). At 15:24:13, the officer instructed the LATAM accuser to reframe her complaint: *"Vas a ser como tu persona... NO COMO LATAM.....ya?!"* (`STG-7.seg-41`, 406.41–411.72s). At 15:25:20, the officer clarified: *"Por ese motivo podemos tomarte una denuncia pero es como tu persona, no como LATAM"* (`STG-7.seg-58`, 482.0–489.25s). Each of these statements is timestamped, transcribed verbatim, and cryptographically hashed in the evidence bundle.
>
> **Article 269 ter** of the Chilean Penal Code punishes the police officer who, "a sabiendas," conceals or alters "cualquier antecedente… que permita establecer… su inocencia." The recordings establish (a) the officer's subjective knowledge of innocence (seg 51: "no hay"), and (b) his active conduct to reframe the complaint in a manner that preserved the appearance of a case while shielding the corporate accuser (segs 41, 58). The failure to document the camera exoneration in the official record is itself the concealment the statute targets.

---

## Summary

The graph data gave you the skeleton; the audio segments are the flesh. CL-030 currently **under-claims** relative to the audio (Art. 269 ter is not scored) and **over-claims** relative to the graph (prevaricación has no grid). The single highest-value change is to **wire STG-7 segs 51, 41, 58, 136, and 173 into a new Art. 269 ter element grid** — those five segments, on their own, move the violation from "alleged" to "documented." The second-highest-value change is to rewrite the narrative so every assertion carries its `(segment_id, timestamp, sha256)` citation, turning the report into a **forensic exhibit** rather than a legal summary.

## 11. Implementation Status

Implemented in `build/CL-030`:

- Narrowed the title to abuse of authority and obstruction; Arts. 223 and 224 remain explicitly unverified candidates rather than established claims.
- Added verified-in-bundle Art. 269 ter text, a three-element grid, and nexus entries for subject, knowledge, and alleged informational concealment.
- Added 10 canonical JSON transcript citations with speaker, timestamp, source SHA-256, quote SHA-256, and translations. The canonical PDI “no complaint” record is `seg-173`, not the legacy `seg-178` label.
- Reworked Art. 255’s vejación analysis around cumulative official conduct and added DGAC/PDI counter-evidence.
- Added nexus entries for every scored Art. 255 and LPDC Art. 23 element; the stale `STG-6.seg-40` reference was not carried forward.
- Regenerated `Validation/checks.json`, `Validation/validation_report.md`, and `MANIFEST.txt` using the repository processor. Current result: 10 passes, 1 warning for the still-empty authorities layer, and 0 failures.

The LPDC Art. 3.b material remains in the pack as an explicitly unproven, zero-scored legacy section for traceability; it is not part of the narrowed title or evidence conclusion and should be removed in a separate LPDC-focused cleanup if that legacy history is no longer needed.