"""End-to-end demo: rebuild the CL-005 refined pack using only the library API.

Run from the repo root:
    python examples/refine_cl005.py

Output goes to ./build/CL-005/ and a zip at ./build/CL-005_refined_pack.zip.

This script doubles as the canonical reference for how each layer is invoked
— each function call here is what an MCP tool would wrap on a 1:1 basis.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from violation_pack import (
    ArticleElementGrid,
    CrossReference,
    Element,
    HtmlTranscriptSource,
    Incident,
    MarkdownFrameworkSource,
    NexusEntry,
    OpenQuestion,
    Violation,
    add_authority_stub,
    add_element_grid,
    attach_confidence,
    build_evidence_layer,
    build_manifest,
    build_nexus_layer,
    build_norms_layer,
    copy_source_into_bundle,
    run_pipeline,
    write_violation_json,
    zip_bundle,
)

HERE = Path(__file__).parent
SOURCE_DIR = HERE / "cl005_source"
BUILD_ROOT = HERE.parent / "build"
BUNDLE_ROOT = BUILD_ROOT / "CL-005"


# ---------------------------------------------------------------------------
# Step 0 — Initial violation shell
# ---------------------------------------------------------------------------

violation = Violation(
    violation_id="CL-005",
    title="CCTV Exoneration — PDI Confirms No Aggression, Then Conceals Finding",
    severity="CRITICAL",
    incident=Incident(
        date="2024-07-05",
        location="Santiago Airport (SCL/STG), Chile",
        flight="LA8159",
        operator="LATAM Airlines Brazil (TAM Linhas Aéreas)",
        clock_time_estimate="~15:16 CLT",
        clock_time_confidence="estimated_from_audio_offset",
    ),
    cross_references=[
        CrossReference(ref="CL-001", relation="predicate_calumnia_disproved_by_this_finding"),
        CrossReference(ref="CL-007", relation="narrative_continued_despite_this_finding"),
        CrossReference(ref="CL-011", relation="removal_decision_never_corrected_after"),
        CrossReference(ref="CL-016", relation="disembarkation_letter_repeated_disproved_accusation"),
        CrossReference(ref="CL-017", relation="passenger_never_informed_of_this_finding"),
    ],
    open_questions=[
        OpenQuestion(
            id="OQ-CL005-PDI-PARTE",
            question="Was the parte to DGAC actually issued, and does it omit the exonerating finding?",
            blocks_element="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
            priority="critical",
            obtaining_method="Ley 20.285 Transparencia request to DGAC and PDI",
        ),
        OpenQuestion(
            id="OQ-CL005-CFTV",
            question="Chain of custody for the CCTV footage reviewed by PDI",
            blocks_element="CL.CHIPENCOD.Art.193.8.elem.documento_oficial",
            priority="high",
        ),
    ],
)


# ---------------------------------------------------------------------------
# Step 1 — Wire sources
# ---------------------------------------------------------------------------

# Copy source-of-truth files into the bundle FIRST so the URIs reflect their
# final location.
BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
copy_source_into_bundle(SOURCE_DIR / "timeline_aeropuerto_STG_7.html", BUNDLE_ROOT, "transcripts_dir")
copy_source_into_bundle(SOURCE_DIR / "CHIPENCOD_CP.md", BUNDLE_ROOT, "framework_dir")

transcript = HtmlTranscriptSource(
    path=BUNDLE_ROOT / "Transcripts" / "timeline_aeropuerto_STG_7.html",
    source_id="STG-7",
    bundle_uri="Transcripts/timeline_aeropuerto_STG_7.html",
)
framework = MarkdownFrameworkSource(
    path=BUNDLE_ROOT / "Legal framework" / "CHIPENCOD_CP.md",
    framework_code="CHIPENCOD",
    bundle_uri="Legal framework/CHIPENCOD_CP.md",
)


# ---------------------------------------------------------------------------
# Step 2 — Layer 1: evidence
# ---------------------------------------------------------------------------

segment_specs = [
    {
        "segment_id": "seg-44",
        "role_in_argument": "cctv_review_admission",
        "translation_en": "when you tell him that there is no aggression as you have seen on camera and all that..",
        "transcription_notes": "Spelling 'agression' / 'quando' / 'hai' is verbatim; speaker code-switching with Portuguese influence.",
    },
    {
        "segment_id": "seg-45",
        "role_in_argument": "coaching_directive",
        "translation_en": "You're going to be filing as your person... NOT AS LATAM.....okay?!",
        "transcription_notes": "Speaker label 'PDI/Latam BOSS' reflects transcriber uncertainty.",
    },
    {
        "segment_id": "seg-47",
        "role_in_argument": "no_injury_admission",
        "translation_en": "In this case, on that side, there are no injuries.",
    },
    {
        "segment_id": "seg-55",
        "role_in_argument": "core_exoneration_admission",
        "translation_en": "**But really, an aggression against a person....there is none",
    },
    {
        "segment_id": "seg-57",
        "role_in_argument": "icao_framing_inquiry",
        "translation_en": "**And the issue obviously of...disembarkation and that.. for it to be a disruptive passenger...as declared.. (ICAO?)...",
    },
    {
        "segment_id": "seg-61",
        "role_in_argument": "icao_framing_rejected",
        "translation_en": "**Ehh right, in that sense..right, disruptive passenger..I didn't see it.... I don't declare it**",
        "transcription_notes": "PDI officer expressly declines the 'disruptive passenger' framing.",
    },
    {
        "segment_id": "seg-62",
        "role_in_argument": "personal_vs_corporate_coaching",
        "translation_en": "**** For that reason we can take a complaint from you but it's as your person, not as LATAM..",
        "transcription_notes": "'Por ese motivo' verbalises the causal nexus between the no-aggression finding and the coaching.",
    },
    {
        "segment_id": "seg-75",
        "role_in_argument": "passenger_kept_uninformed",
        "translation_en": "Okay Leandro, I'm going to file the report with the Civil Aviation Directorate, we regret you've lost your flight, this decision was not made by us",
    },
    {
        "segment_id": "seg-177",
        "role_in_argument": "no_complaint_on_record_admission",
        "translation_en": "they in the system are going to have that you arrived on time, that there's no complaint against you...",
    },
]
violation = build_evidence_layer(violation, transcript, segment_specs)


# ---------------------------------------------------------------------------
# Step 3 — Layer 2: norms
# ---------------------------------------------------------------------------

article_specs = [
    {
        "article_id": "CL.CHIPENCOD.T4.C3.Art.193",
        "article_name": "Falsedad cometida por empleado público",
        "subsections_invoked": ["8"],
        "verbatim_excerpt": "8.° Ocultando en perjuicio del Estado o de un particular cualquier documento oficial.",
        "duty_bearer": "state",
        "norm_type": "penalty",
        "applicability": "direct",
        "applicability_rationale": (
            "PDI officers had a duty to memorialise the CCTV-review finding in an official parte. "
            "The verbal finding at seg-55, made in execution of their office, was an act of the office; "
            "its non-inclusion in the parte mentioned at seg-75, combined with the immediately preceding "
            "coaching at seg-45/seg-62, supports the modality of ocultación under numeral 8."
        ),
    },
    {
        "article_id": "CL.CHIPENCOD.T4.C6.Art.211",
        "article_name": "Acusación o denuncia calumniosa",
        "subsections_invoked": [],
        "verbatim_excerpt": (
            "Art. 211. El que imputare falsamente a alguna persona haber cometido un crimen o simple delito, "
            "siendo sabedor de la falsedad de la imputación, o el que la hiciere de malicia, incurrirá en las "
            "penas de reclusión menor en sus grados mínimo a medio y multa de once a quince unidades tributarias mensuales."
        ),
        "duty_bearer": "state",
        "norm_type": "penalty",
        "applicability": "indirect_predicate",
        "applicability_rationale": (
            "Invoked not against PDI but as the predicate offence whose falsity was established by PDI's own "
            "CCTV review (seg-55). Anchors materiality of the Art. 193(8) concealment."
        ),
    },
]

candidate_specs = [
    {
        "candidate_article_id": "CL.CHIPENCOD.Art.269bis_or_ter",
        "candidate_name": "Obstrucción a la investigación (real article number TBD)",
        "framework_cache_status": "not_in_bundle",
        "verification_required": [
            "Fetch CHIPENCOD article body for 269 bis and 269 ter from bcn.cl/leychile",
            "Determine the correct article and whether the seg-45/seg-50/seg-62 conduct fits its elements",
        ],
        "history_note": (
            "Schema 2.1 had CL.CPCL.C1.Art.497 (fabricated — Art. 497 concerns ganado en heredad ajena) "
            "later replaced with Art. 269_ter framed as 'denegación de auxilio'. That replacement is also "
            "inaccurate: denegación de auxilio is Arts. 253–254 CP; Art. 269 ter concerns obstrucción a la "
            "investigación. Both prior citations are withdrawn pending fresh fetch of the framework."
        ),
    },
]

violation = build_norms_layer(violation, framework, article_specs, candidate_specs)


# ---------------------------------------------------------------------------
# Step 4 — Layer 3: element grid for Art. 193(8)
# ---------------------------------------------------------------------------

art193_grid = ArticleElementGrid(
    article_id="CL.CHIPENCOD.T4.C3.Art.193",
    article_short="Art. 193 N° 8 CP — ocultación de documento oficial por empleado público",
    elements=[
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.sujeto_activo_calificado",
            label="Sujeto activo: empleado público",
            proof_status="established",
            proof_evidence_segments=["STG-7.seg-44", "STG-7.seg-55", "STG-7.seg-61", "STG-7.seg-62"],
            argument_es="Los funcionarios 'PDI-OF' son oficiales de PDI, empleados públicos bajo Art. 260 CP y DL 2.460.",
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.abuso_del_oficio",
            label="Abuso del oficio",
            proof_status="established",
            proof_evidence_segments=["STG-7.seg-44", "STG-7.seg-62", "STG-7.seg-75"],
            argument_es="La revisión del CFTV, la toma o no-toma de denuncia, y la emisión del parte a DGAC son actos del servicio.",
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.acto_del_oficio",
            label="Acto del oficio cuya constancia debía generarse",
            proof_status="established",
            proof_evidence_segments=["STG-7.seg-44", "STG-7.seg-55", "STG-7.seg-61"],
            argument_es="La revisión del CFTV es diligencia investigativa; el deber funcional (CPP Art. 175 ss.) obliga a consignar su resultado en el parte.",
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
            label="Modalidad típica: ocultación",
            proof_status="strong",
            proof_evidence_segments=["STG-7.seg-45", "STG-7.seg-62", "STG-7.seg-75"],
            argument_es="Tres actos: directiva a LATAM (seg-45/seg-62), conjunción causal 'por ese motivo' admitiendo dolo, parte sin mención del hallazgo (seg-75).",
            weaknesses=["seg-75 omission depends on OQ-CL005-PDI-PARTE for full proof"],
            open_questions=["OQ-CL005-PDI-PARTE"],
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.documento_oficial",
            label="Objeto material: documento oficial",
            proof_status="contested",
            proof_evidence_segments=["STG-7.seg-75", "STG-7.seg-177"],
            argument_es="Si el parte se emitió y omitió el hallazgo, es ocultación por omisión de contenido. Sin verificar OQ-CL005-PDI-PARTE el elemento queda contested.",
            weaknesses=[
                "Depends on doctrine of 'ocultación por omisión de contenido' — needs verified authority",
                "seg-177 'no hay denuncia en tu contra' admits a benign reading too",
            ],
            open_questions=["OQ-CL005-PDI-PARTE", "OQ-CL005-CFTV"],
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.perjuicio_particular",
            label="Perjuicio a un particular",
            proof_status="strong",
            proof_evidence_segments=["STG-7.seg-75"],
            argument_es="Pérdida del vuelo, remoción, prohibición y narrativa continuada (CL-007, CL-016, CL-017).",
        ),
        Element(
            element_id="CL.CHIPENCOD.Art.193.8.elem.dolo",
            label="Tipicidad subjetiva: dolo",
            proof_status="established",
            proof_evidence_segments=["STG-7.seg-62"],
            argument_es="'Por ese motivo' en seg-62 verbaliza directamente el nexo mental entre lo sabido y lo decidido.",
        ),
    ],
)
violation = add_element_grid(violation, art193_grid)


# ---------------------------------------------------------------------------
# Step 5 — Layer 4: nexus matrix
# ---------------------------------------------------------------------------

nexus_entries = [
    NexusEntry(fact_id="STG-7.seg-55", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.sujeto_activo_calificado",
               nexus_type="speaker_identification", strength="high",
               rationale_oneline="Speaker label 'PDI-OF' identifies actor as empleado público."),
    NexusEntry(fact_id="STG-7.seg-44", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.abuso_del_oficio",
               nexus_type="functional_context", strength="high",
               rationale_oneline="CCTV review performed in execution of police function at airport intervention."),
    NexusEntry(fact_id="STG-7.seg-55", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.acto_del_oficio",
               nexus_type="direct_admission", strength="high",
               rationale_oneline="Statement confirms finding produced in exercise of office."),
    NexusEntry(fact_id="STG-7.seg-61", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.acto_del_oficio",
               nexus_type="corroborating_admission", strength="high",
               rationale_oneline="Independent declination of ICAO 'disruptive passenger' framing."),
    NexusEntry(fact_id="STG-7.seg-62", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
               nexus_type="active_concealment_directive", strength="high",
               rationale_oneline="'Por ese motivo' links the no-aggression finding to the personal-complaint directive."),
    NexusEntry(fact_id="STG-7.seg-45", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.modalidad_ocultacion",
               nexus_type="active_concealment_directive", strength="medium",
               rationale_oneline="Speaker attribution ambiguous; strength downgraded pending identification."),
    NexusEntry(fact_id="STG-7.seg-75", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.documento_oficial",
               nexus_type="circumstantial_omission", strength="medium",
               rationale_oneline="Passenger told of outcome without being told the exonerating finding."),
    NexusEntry(fact_id="STG-7.seg-177", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.documento_oficial",
               nexus_type="system_state_corroboration", strength="medium",
               rationale_oneline="No formal complaint reached the system — consistent with concealment thesis."),
    NexusEntry(fact_id="STG-7.seg-75", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.perjuicio_particular",
               nexus_type="harm_crystallization", strength="high",
               rationale_oneline="Passenger told he has lost flight without being told the concealed finding."),
    NexusEntry(fact_id="STG-7.seg-62", norm_id="CL.CHIPENCOD.T4.C3.Art.193",
               element_id="CL.CHIPENCOD.Art.193.8.elem.dolo",
               nexus_type="contemporaneous_admission_of_intent", strength="high",
               rationale_oneline="'Por ese motivo' verbalises the mental nexus — most direct dolo evidence."),
]
violation = build_nexus_layer(violation, nexus_entries)


# ---------------------------------------------------------------------------
# Step 6 — Layer 5: authorities (stubs only; verified=False)
# ---------------------------------------------------------------------------

violation = add_authority_stub(
    violation, authority_id="AUTH-CS-193-N8",
    type_="jurisprudence",
    supports=["CL.CHIPENCOD.Art.193.8.elem.documento_oficial"],
    research_query="Corte Suprema — Art. 193 N° 8 — concepto de 'documento oficial' — alcance al parte policial",
    proposition_to_verify="Verbal finding made during an official act becomes a documento oficial for Art. 193(8) once a written record is or should have been generated.",
    verification_protocol="Search Poder Judicial (pjud.cl) and BCN; require rol, sala, fecha, ministro redactor before flipping verified:true.",
    fabrication_risk_note="Do NOT auto-populate rol numbers from LLM memory.",
)
violation = add_authority_stub(
    violation, authority_id="AUTH-DOCT-ETCHEBERRY-PE",
    type_="doctrine",
    supports=["CL.CHIPENCOD.Art.193"],
    research_query="Etcheberry — Derecho Penal Parte Especial — alcance de 'ocultación' en Art. 193 N° 8",
    proposition_to_verify="Ocultación bajo Art. 193 N° 8 comprende la no incorporación al documento debido de un dato que debía contener.",
)


# ---------------------------------------------------------------------------
# Step 7 — Derive confidence
# ---------------------------------------------------------------------------

violation = attach_confidence(violation)


# ---------------------------------------------------------------------------
# Step 8 — Serialize, validate, manifest, zip
# ---------------------------------------------------------------------------

write_violation_json(violation, BUNDLE_ROOT)

report = run_pipeline(
    violation,
    transcripts={"STG-7": transcript},
    frameworks={"CHIPENCOD": framework},
)

# Persist validation outputs
(BUNDLE_ROOT / "Validation").mkdir(parents=True, exist_ok=True)
(BUNDLE_ROOT / "Validation" / "checks.json").write_text(
    report.model_dump_json(indent=2), encoding="utf-8"
)

build_manifest(BUNDLE_ROOT)
out_zip = zip_bundle(BUNDLE_ROOT, BUILD_ROOT / "CL-005_refined_pack.zip")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"Bundle written to: {BUNDLE_ROOT}")
print(f"Zip:               {out_zip}")
print(f"Confidence:        {violation.confidence.value}  (formula: {violation.confidence.derivation_formula})")
print(f"Validation:        {report.summary}")
for c in report.checks:
    marker = {"pass": "✓", "warn": "!", "fail": "✗"}[c.status]
    print(f"  {marker} {c.check_id} {c.name}: {c.status}")
