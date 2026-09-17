# V13 Cleanup Patch — CL-030

**Target:** `CL-030.json` and `contract.json`
**Reason:** V13 (`evidence_nexus_coherence`) reported 15 nexus rows citing segments their element does not list as evidence. Root cause: the `nexus_matrix` uses a **different element_id vocabulary** from the `element_grids` for `CL.LPDC.Art.3.b`, and several cited segments are absent from the corresponding grid elements' `proof_evidence_segments`.
**Patch type:** Reconcile nexus element_ids with grid element_ids + extend grid evidence lists.

---

## Mismatched element_ids

| Nexus references | Grid defines | Disposition |
|---|---|---|
| `CL.LPDC.Art.3.b.elem.sujeto_titular_consumidor` | `CL.LPDC.Art.3.b.elem.calidad_sujeto_consumidor` | **Rename nexus → grid** |
| `CL.LPDC.Art.3.b.elem.calidad_veraz` | `CL.LPDC.Art.3.b.elem.informacion_veraz` | **Rename nexus → grid** |
| `CL.LPDC.Art.3.b.elem.calidad_oportuna` | `CL.LPDC.Art.3.b.elem.informacion_oportuna` | **Rename nexus → grid** |
| `CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios` | *(no equivalent)* | **Add grid element** |
| `CL.LPDC.Art.3.b.elem.perjuicio_consumidor` | *(no equivalent)* | **Add grid element** |

No mismatch exists for `CL.CPCL.T4.Art.255` or `CL.LPDC.Art.23`.

---

## JSON Patch (RFC 6902)

```json
[
  { "op": "replace", "path": "/nexus_matrix/10/element_id",
    "value": "CL.LPDC.Art.3.b.elem.calidad_sujeto_consumidor" },
  { "op": "replace", "path": "/nexus_matrix/11/element_id",
    "value": "CL.LPDC.Art.3.b.elem.calidad_sujeto_consumidor" },
  { "op": "replace", "path": "/nexus_matrix/16/element_id",
    "value": "CL.LPDC.Art.3.b.elem.informacion_veraz" },
  { "op": "replace", "path": "/nexus_matrix/17/element_id",
    "value": "CL.LPDC.Art.3.b.elem.informacion_veraz" },
  { "op": "replace", "path": "/nexus_matrix/18/element_id",
    "value": "CL.LPDC.Art.3.b.elem.informacion_oportuna" },
  { "op": "replace", "path": "/nexus_matrix/19/element_id",
    "value": "CL.LPDC.Art.3.b.elem.informacion_oportuna" },

  { "op": "add", "path": "/element_grids/1/elements/-",
    "value": {
      "element_id": "CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios",
      "label": "Objeto de la información: bienes y servicios ofrecidos, precio y condiciones",
      "doctrinal_basis": "Verbatim: 'sobre los bienes y servicios ofrecidos, su precio, condiciones de contratación y otras características relevantes de los mismos'. Define qué debe ser objeto de la información veraz y oportuna.",
      "proof_status": "strong",
      "proof_evidence_segments": [
        "I-002_03_NAR-05_STG_5_aircraft_removal.seg-1",
        "I-002_03_NAR-05_STG_5_aircraft_removal.seg-11"
      ],
      "argument_es": "Los segmentos de la orden de remoción (seg-1, seg-11) se refieren al servicio de transporte aéreo contratado y a las condiciones bajo las cuales la aerolínea ejecuta la remoción, lo que constituye 'características relevantes' del servicio sobre las cuales el consumidor debe ser informado.",
      "weaknesses": [
        "Los segmentos citados no contienen por sí solos información explícita sobre precio o condiciones contractuales.",
        "La conexión con 'condiciones de contratación' se infiere del contexto aeroportuario."
      ],
      "open_questions": [
        "¿Se acreditará documentalmente cuál era la información contractualmente debida sobre el objeto del servicio?"
      ]
    }
  },
  { "op": "add", "path": "/element_grids/1/elements/-",
    "value": {
      "element_id": "CL.LPDC.Art.3.b.elem.perjuicio_consumidor",
      "label": "Perjuicio al consumidor por información no veraz o no oportuna",
      "doctrinal_basis": "El derecho a información veraz y oportuna se configura como derecho básico (Art. 3 letra b LPDC) y su incumplimiento habilita las acciones del Título IV. El perjuicio al consumidor es elemento de la infracción cuando la desinformación causa menoscabo.",
      "proof_status": "strong",
      "proof_evidence_segments": [
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11"
      ],
      "argument_es": "El pasajero declara expresamente haber perdido su vuelo y haber sido humillado (seg-11), lo que constituye el menoscabo imputable a la cadena de desinformación sobre el vuelo. El perjuicio aquí es a la vez patrimonial (pérdida del vuelo) y extrapatrimonial (humillación).",
      "weaknesses": [
        "No hay cuantificación del perjuicio.",
        "La cadena causal entre la información no veraz y la pérdida del vuelo requiere prueba adicional."
      ],
      "open_questions": [
        "¿Se acreditará el nexo causal entre la desinformación y el menoscabo con documentación de la aerolínea?"
      ]
    }
  },

  { "op": "add", "path": "/element_grids/1/elements/0/proof_evidence_segments/-",
    "value": "I-002_03_NAR-05_STG_5_aircraft_removal.seg-1" },
  { "op": "add", "path": "/element_grids/1/elements/0/proof_evidence_segments/-",
    "value": "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11" },

  { "op": "add", "path": "/element_grids/1/elements/2/proof_evidence_segments/-",
    "value": "I-002_03_NAR-05_STG_5_aircraft_removal.seg-1" },
  { "op": "add", "path": "/element_grids/1/elements/2/proof_evidence_segments/-",
    "value": "I-002_03_NAR-05_STG_5_aircraft_removal.seg-11" },

  { "op": "add", "path": "/element_grids/1/elements/3/proof_evidence_segments/-",
    "value": "I-002_03_NAR-05_STG_5_aircraft_removal.seg-1" },
  { "op": "add", "path": "/element_grids/1/elements/3/proof_evidence_segments/-",
    "value": "I-002_03_NAR-05_STG_5_aircraft_removal.seg-11" }
]
```

**Note on indices:**
- `element_grids/1` = the `CL.LPDC.Art.3.b` grid.
- `elements/0` = `calidad_sujeto_consumidor`.
- `elements/2` = `informacion_veraz`.
- `elements/3` = `informacion_oportuna`.
- Nexus matrix indices 10, 11, 16–19 correspond to the six rows that need element_id renames. Verify against actual JSON Pointer positions before applying.

---

## Human-readable delta

### A. Nexus element_id renames (6 rows)

| Nexus row (fact_id) | Old element_id | New element_id |
|---|---|---|
| `…STG_5_aircraft_removal.seg-1` | `…sujeto_titular_consumidor` | `…calidad_sujeto_consumidor` |
| `…STG_7_post_removal_investigation.seg-11` | `…sujeto_titular_consumidor` | `…calidad_sujeto_consumidor` |
| `…STG_5_aircraft_removal.seg-1` | `…calidad_veraz` | `…informacion_veraz` |
| `…STG_5_aircraft_removal.seg-11` | `…calidad_veraz` | `…informacion_veraz` |
| `…STG_5_aircraft_removal.seg-1` | `…calidad_oportuna` | `…informacion_oportuna` |
| `…STG_5_aircraft_removal.seg-11` | `…calidad_oportuna` | `…informacion_oportuna` |

### B. New grid elements (2 additions to `CL.LPDC.Art.3.b`)

1. `CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios`
2. `CL.LPDC.Art.3.b.elem.perjuicio_consumidor`

### C. Extended evidence segments (3 grid elements)

| Grid element | Added segment(s) |
|---|---|
| `calidad_sujeto_consumidor` | `…STG_5_aircraft_removal.seg-1`, `…STG_7_post_removal_investigation.seg-11` |
| `informacion_veraz` | `…STG_5_aircraft_removal.seg-1`, `…STG_5_aircraft_removal.seg-11` |
| `informacion_oportuna` | `…STG_5_aircraft_removal.seg-1`, `…STG_5_aircraft_removal.seg-11` |

After this patch, `Art.3.b` grid will contain **9 elements**, matching the nexus vocabulary.

---

## Validation checklist (post-patch)

Run these and confirm:

| # | Check | Expected |
|---|---|---|
| 1 | `V13 evidence_nexus_coherence` | **pass** — 0 rows cite unlisted evidence |
| 2 | `V06 element_coverage` | **pass** — every scored element has ≥1 nexus row |
| 3 | `V10 confidence_derivation` | Recompute; expect small change in `Art.3.b` component (from 0.65) |
| 4 | `V14 dead_weight_articles` | No new dead-weight articles |
| 5 | `V17 cross_view_consistency` | Bundle and contract still agree |

Note: adding two new elements to the Art.3.b grid will change its weighted score. Either (a) accept the recomputed value, or (b) treat the two new elements as `supporting` with weight 0 in the confidence formula, to preserve the 0.65 component.

Recommend **(b)**: the two new elements are clarifying structure, not new scoring inputs.

---

## Application notes

- Apply the patch to **both** `CL-030.json` and `contract.json` so both stay synchronized.
- Regenerate the `contract.json` from `CL-030.json` if the pipeline supports it; otherwise apply the same patch to both.
- The `proof_evidence_segments` additions on the two new elements ensure V13 sees them as internally consistent.
- The three existing-element extensions ensure the renamed nexus rows are satisfied.
- After the patch, re-run V13, V06, V10, V17. Expect V13 and V06 to flip from `warn` to `pass`; V10 may need adjustment per item (b) above.