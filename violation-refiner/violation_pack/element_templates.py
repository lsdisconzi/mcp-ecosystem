"""Canonical element vocabulary for the articles this corpus cites.

Why this exists
---------------
The enrichment stage asks an LLM to decompose each article into its doctrinal
elements, and two separate calls — one for the grid, one for the nexus matrix —
must agree on the element ids. They routinely do not. The CL-005 v3 bundle
shipped a grid whose ids ended in ``elem.sujeto_activo_empleado_publico`` and a
nexus matrix referencing ``elem.sujeto_activo``; V11 catches such a bundle at
the enrichment seam, but a bundle written by any other route carries the drift
silently until someone reads the JSON by hand.

Templates close this at the source. For an article with a known template, the
element set and the spelling of every element id are fixed *before* the prompt
is written, so the LLM's job is to score elements rather than name them. An
article with no template keeps its free-form behaviour: the registry is a
vocabulary, not a gate.

Id shape
--------
``<article_id>[.<numeral>].elem.<key>``

Examples::

    CL.CHIPENCOD.T4.C3.Art.193.8.elem.modalidad_ocultacion
    CL.CPCL.C1.Art.255.elem.vejacion_injusta
    CL.CC.Art.2314.elem.nexo_causal

The article_id prefix is whatever the bundle's ``established_articles[]`` uses
for that article — the template does **not** rewrite it, because two bundles in
this corpus spell the same article as ``CL.CHIPENCOD.T4.C3.Art.193`` and as
``CL.CHIPENCOD.Art.193`` and the hierarchy segments matter to neither the
element vocabulary nor the case. The template only fixes the *suffix*, and
:func:`canonicalize_element_ids` is the helper a caller uses to rewrite the
prefix to whichever spelling it prefers.

The numeral segment is present iff the caller supplies one. It is ``"8"`` for
Art. 193 N°8, ``"b"`` for LPDC Art. 3 letra b), ``"3"`` for CPR Art. 19 N°3.
When an article invokes several numerals at once (CACH Art. 133 numerals 1 and
2 in CL-005), the caller passes ``numeral=None`` and the elements are composed
without a segment — which is what that bundle already does.

Lookup is by ``(framework, number, numeral)``, not by full article id, so the
hierarchy-segment drift above does not create duplicate registry entries. A
small alias table maps the vault's legacy framework codes (``CHIPENCOD``,
``CP``) onto the codes the templates are registered under, because the corpus
uses both spellings for the same code.

The ``numeral=None`` fallback
-----------------------------
:func:`find_template` carries one deliberate relaxation that the review
surfaced: when the caller supplies no numeral and the registry holds exactly
one registration for ``(framework, number)`` regardless of numeral, that
registration is returned. Without it, a bundle whose ``subsections_invoked`` is
empty for Art. 193 N°8 silently misses the numeral-scoped template, and the
element vocabulary reverts to free-form. The relaxation does *not* fire when
the caller supplied a numeral that does not match — an explicit numeral that
misses means "no template".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from .models import ArticleElementGrid


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ElementSpec:
    """One doctrinal element of an article.

    ``doctrinal_basis`` is a short paraphrase or a verbatim clause — it tells
    the enrichment stage what the element *is*, so the LLM's argument for a
    proof status has a fixed anchor rather than a free-floating label. It is
    not a legal citation and must not be treated as one.
    """
    key: str
    label: str
    doctrinal_basis: str
    required: bool = True


@dataclass(frozen=True)
class ArticleTemplate:
    """The fixed element vocabulary for one ``(framework, number, numeral)``."""

    framework: str
    number: str
    numeral: str | None
    element_short: str
    elements: tuple[ElementSpec, ...]
    notes: str = ""

    # -- composition -------------------------------------------------------

    def element_id(self, article_id: str, spec: ElementSpec) -> str:
        parts = [article_id]
        if self.numeral:
            parts.append(self.numeral)
        parts.extend(("elem", spec.key))
        return ".".join(parts)

    def element_ids(self, article_id: str) -> dict[str, str]:
        """``{element_key: full_element_id}`` for this article_id prefix."""
        return {spec.key: self.element_id(article_id, spec) for spec in self.elements}

    def spec_for(self, key: str) -> ElementSpec | None:
        for spec in self.elements:
            if spec.key == key:
                return spec
        return None

    def keys(self) -> frozenset[str]:
        return frozenset(spec.key for spec in self.elements)

    def required_keys(self) -> frozenset[str]:
        return frozenset(spec.key for spec in self.elements if spec.required)

    def as_prompt_block(self, article_id: str) -> dict:
        """The template as the enrichment prompt expects it.

        The prompt does not need to know the numeral-composition rule, only
        the ids it must reproduce verbatim, so the block carries the *final*
        strings, not the pieces. This is deliberate: an LLM asked to compose
        an id from parts will eventually compose it slightly differently, and
        the whole point of the template is that it does not have to.
        """
        return {
            "article_id": article_id,
            "element_short": self.element_short,
            "notes": self.notes,
            "elements": [
                {
                    "element_id": self.element_id(article_id, spec),
                    "label": spec.label,
                    "doctrinal_basis": spec.doctrinal_basis,
                    "required": spec.required,
                }
                for spec in self.elements
            ],
        }


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

TEMPLATES: dict[tuple[str, str, str | None], ArticleTemplate] = {}


def _register(template: ArticleTemplate) -> ArticleTemplate:
    key = (template.framework, template.number, template.numeral)
    if key in TEMPLATES:
        raise RuntimeError(f"duplicate template registration for {key}")
    TEMPLATES[key] = template
    return template


# -- Chilean Penal Code, Art. 193 N°8 — ocultación de documento oficial -----
_register(ArticleTemplate(
    framework="CPCL",
    number="193",
    numeral="8",
    element_short=(
        "Art. 193 N° 8 — Ocultación de documento oficial por empleado público "
        "(Código Penal)"
    ),
    elements=(
        ElementSpec(
            "sujeto_activo_empleado_publico",
            "Sujeto activo: empleado público",
            "Verbatim: 'El empleado público'. Funcionarios PDI, DGAC y "
            "asimilados están dentro del tipo.",
        ),
        ElementSpec(
            "abuso_del_oficio",
            "Ejercicio de funciones (abuso del oficio)",
            "La conducta se comete 'desempeñando un acto del servicio' o en el "
            "ejercicio del cargo, desviando la competencia hacia un fin ilícito.",
        ),
        ElementSpec(
            "acto_del_oficio",
            "Acto del oficio",
            "Debe existir un acto propio del cargo (parte, informe, diligencia, "
            "constancia) sobre el que recae la conducta.",
        ),
        ElementSpec(
            "modalidad_ocultacion",
            "Modalidad típica: ocultar documento oficial",
            "Verbatim: 'Ocultando ... cualquier documento oficial'. La doctrina "
            "admite tanto la supresión material de un documento existente como "
            "la omisión deliberada de la constancia que debía practicarse.",
        ),
        ElementSpec(
            "objeto_material_documento_oficial",
            "Objeto material: documento oficial",
            "'Cualquier documento oficial' en sentido amplio: partes policiales, "
            "informes de diligencia, actas de constatación.",
        ),
        ElementSpec(
            "resultado_perjuicio",
            "Resultado: perjuicio al Estado o a un particular",
            "Verbatim: 'en perjuicio del Estado o de un particular'. Actual o "
            "potencial, material o moral.",
        ),
        ElementSpec(
            "tipicidad_subjetiva_dolo",
            "Tipicidad subjetiva: dolo",
            "Dolo directo: conocimiento de la oficialidad del documento y "
            "voluntad de ocultarlo.",
        ),
    ),
    notes="Tipo de resultado: 'resultado_perjuicio' no puede omitirse.",
))


# -- Chilean Penal Code, Art. 211 — denuncia calumniosa ----------------------
_register(ArticleTemplate(
    framework="CPCL",
    number="211",
    numeral=None,
    element_short="Art. 211 — Acusación o denuncia calumniosa (Código Penal)",
    elements=(
        ElementSpec(
            "imputacion_falsa_crimen",
            "Imputación falsa de crimen o simple delito",
            "Verbatim: 'imputare falsamente a alguna persona haber cometido "
            "un crimen o simple delito'.",
        ),
        ElementSpec(
            "hecha_ante_autoridad",
            "Hecha ante autoridad (agravante)",
            "Verbatim: 'Si la falsa imputación se hiciere ante la autoridad "
            "judicial o ministerio público, la pena se aumentará en un grado'. "
            "La PDI es autoridad policial para estos efectos.",
        ),
        ElementSpec(
            "elemento_subjetivo_falsedad",
            "Elemento subjetivo: sabedor de falsedad o malicia",
            "Verbatim: 'siendo sabedor de la falsedad de la imputación, o el "
            "que la hiciere de malicia'.",
        ),
    ),
))


# -- Chilean Penal Code, Art. 255 — vejaciones injustas ----------------------
_register(ArticleTemplate(
    framework="CPCL",
    number="255",
    numeral=None,
    element_short="Art. 255 — Vejaciones injustas por empleado público (Código Penal)",
    elements=(
        ElementSpec(
            "sujeto_activo_empleado_publico",
            "Sujeto activo: empleado público",
            "Verbatim: 'El empleado público'.",
        ),
        ElementSpec(
            "acto_del_servicio",
            "Acto del servicio",
            "Verbatim: 'desempeñando un acto del servicio'.",
        ),
        ElementSpec(
            "vejacion_injusta",
            "Vejación injusta",
            "Verbatim: 'cometiere cualquier vejación injusta'. La doctrina "
            "admite la acumulación de conductas cuando el patrón de trato "
            "es injusto, sin exigir un agravio aislado.",
        ),
        ElementSpec(
            "sujeto_pasivo_personas",
            "Sujeto pasivo: personas",
            "Verbatim: 'contra las personas'.",
        ),
        ElementSpec(
            "dolo",
            "Dolo",
            "Se requiere dolo. La doctrina admite el dolo eventual cuando el "
            "agente se representa el resultado típico como posible y actúa "
            "aceptándolo.",
        ),
    ),
))


# -- Chilean Penal Code, Art. 269 ter — obstrucción por funcionario ----------
_register(ArticleTemplate(
    framework="CPCL",
    number="269_ter",
    numeral=None,
    element_short=(
        "Art. 269 ter — Obstrucción a la investigación por funcionario "
        "(Código Penal)"
    ),
    elements=(
        ElementSpec(
            "sujeto_activo_funcionario_policial",
            "Sujeto activo: funcionario policial",
            "Verbatim: 'El funcionario policial, el fiscal del Ministerio "
            "Público, o el abogado asistente del fiscal'.",
        ),
        ElementSpec(
            "conocimiento_inocencia",
            "Conocimiento de la inocencia",
            "Verbatim: 'a sabiendas' y 'su inocencia'. Se acredita por la "
            "constancia verbal del funcionario.",
        ),
        ElementSpec(
            "ocultamiento_o_alteracion",
            "Ocultar, alterar o destruir un antecedente",
            "Verbatim: 'ocultare, alterare o destruyere cualquier antecedente, "
            "objeto o documento, o imagen o sonido contenido en sistemas de "
            "registro y almacenamiento audiovisual'.",
        ),
    ),
))


# -- Chilean Penal Code, Art. 412 — calumnia ---------------------------------
_register(ArticleTemplate(
    framework="CPCL",
    number="412",
    numeral=None,
    element_short="Art. 412 — Calumnia (Código Penal)",
    elements=(
        ElementSpec(
            "imputacion_delito_determinado",
            "Imputación de un delito determinado",
            "Verbatim: 'la imputación de un delito determinado'.",
        ),
        ElementSpec(
            "falsedad_imputacion",
            "Falsedad de la imputación",
            "Verbatim: 'pero falso'. Debe acreditarse por medio independiente.",
        ),
        ElementSpec(
            "delito_perseguible_de_oficio",
            "Delito perseguible de oficio",
            "Verbatim: 'que pueda actualmente perseguirse de oficio'.",
        ),
    ),
))


# -- Chilean Civil Code, Art. 2314 — responsabilidad extracontractual --------
_register(ArticleTemplate(
    framework="CC",
    number="2314",
    numeral=None,
    element_short="Art. 2314 — Responsabilidad extracontractual (Código Civil)",
    elements=(
        ElementSpec(
            "comision_delito_o_cuasidelito",
            "Comisión de un delito o cuasidelito",
            "Verbatim: 'El que ha cometido un delito o cuasidelito'. El hecho "
            "ilícito puede ser penal o civil.",
        ),
        ElementSpec(
            "dano_inferido",
            "Daño inferido a otro",
            "Verbatim: 'que ha inferido daño a otro'. El daño puede ser "
            "patrimonial o moral.",
        ),
        ElementSpec(
            "nexo_causal",
            "Nexo causal",
            "Relación de causalidad entre el hecho ilícito y el daño. No se "
            "exige intención respecto del daño.",
        ),
        ElementSpec(
            "responsabilidad_vicaria",
            "Responsabilidad vicaria",
            "Cuando el autor material es un dependiente, el empleador responde "
            "por el hecho ajeno (CC Art. 2320; CACH Art. 171 para aerolíneas).",
        ),
    ),
))


# -- Chilean Aeronautical Code, Art. 133 — denegación de embarque ------------
_register(ArticleTemplate(
    framework="CACH",
    number="133",
    numeral=None,
    element_short="Art. 133 — Denegación de embarque (Código Aeronáutico)",
    elements=(
        ElementSpec(
            "sujeto_activo_transportador",
            "Sujeto activo: transportador aéreo",
            "El transportador, actuando por medio de su personal, es el sujeto "
            "activo obligado por el artículo.",
        ),
        ElementSpec(
            "sujeto_pasivo_pasajero",
            "Sujeto pasivo: pasajero con contrato vigente",
            "Se requiere una relación de transporte vigente al momento del acto.",
        ),
        ElementSpec(
            "acto_denegacion_embarque",
            "Acto de denegación de embarque",
            "Verbatim: 'denegar el embarque'. La remoción forzada contra la "
            "voluntad del pasajero constituye denegación.",
        ),
        ElementSpec(
            "causa_invocada_falsa",
            "Causa invocada comprobadamente falsa",
            "La causa invocada por el transportador debe ser real. Una causa "
            "posteriormente desmentida no sostiene la denegación.",
        ),
        ElementSpec(
            "omision_opciones",
            "Omisión de ofrecer las opciones del N° 1",
            "Verbatim: 'A elección del pasajero: a) Embarcar en el siguiente "
            "vuelo... b) El reembolso del monto total pagado'.",
        ),
        ElementSpec(
            "omision_compensacion",
            "Omisión de la compensación obligatoria (N° 2)",
            "Verbatim: 'el transportador deberá ofrecer una compensación al "
            "pasajero afectado con la denegación de embarque'.",
        ),
        ElementSpec(
            "persistencia_registro_falso",
            "Persistencia del registro falso",
            "Mantener la causa desmentida en la documentación oficial emitida "
            "después de conocido el desmentido agrava la infracción.",
        ),
    ),
))


# -- Chilean Consumer Protection Act, Art. 23 — infracción por negligencia ---
_register(ArticleTemplate(
    framework="LPDC",
    number="23",
    numeral=None,
    element_short="Art. 23 — Infracción por negligencia causante de menoscabo (LPDC)",
    elements=(
        ElementSpec(
            "proveedor",
            "Sujeto activo: proveedor",
            "Verbatim: 'el proveedor'. Se acredita por la actividad comercial "
            "del demandado.",
        ),
        ElementSpec(
            "venta_o_prestacion",
            "Venta de un bien o prestación de un servicio",
            "Verbatim: 'en la venta de un bien o en la prestación de un servicio'.",
        ),
        ElementSpec(
            "negligencia",
            "Negligencia del proveedor",
            "Verbatim: 'actuando con negligencia'. El estándar de diligencia "
            "exigible al proveedor depende del protocolo aplicable.",
        ),
        ElementSpec(
            "menoscabo",
            "Menoscabo al consumidor",
            "Verbatim: 'causa menoscabo al consumidor'. Puede ser patrimonial "
            "o extrapatrimonial.",
        ),
        ElementSpec(
            "falla_calidad",
            "Falla o deficiencia en la calidad o seguridad del servicio",
            "Verbatim: 'debido a fallas o deficiencias en la calidad, cantidad, "
            "identidad, sustancia, procedencia, seguridad, peso o medida'.",
        ),
    ),
))


def _validate_registry() -> None:
    """Fail at import when a template is internally inconsistent.

    Runs once, at module load, so a typo in a template is a startup error
    rather than a missing check three functions later. The checks mirror what
    a validator would catch — unique keys, snake_case, at least one required
    element — but running them here means a bundle cannot reach the pipeline
    with a template that was never tested.
    """
    snake_case = re.compile(r"^[a-z][a-z0-9_]*$")
    for key, template in TEMPLATES.items():
        if not template.elements:
            raise RuntimeError(f"template {key} declares no elements")
        keys = [spec.key for spec in template.elements]
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"template {key} has duplicate element keys: {keys}")
        if not any(spec.required for spec in template.elements):
            raise RuntimeError(
                f"template {key} declares no required elements; a template that "
                "requires nothing cannot be checked"
            )
        for spec in template.elements:
            if not snake_case.fullmatch(spec.key):
                raise RuntimeError(
                    f"template {key}: element key {spec.key!r} is not snake_case"
                )


_validate_registry()


# ---------------------------------------------------------------------------
# Framework-code aliases
# ---------------------------------------------------------------------------

#: Legacy framework codes the vault uses for a code the templates are
#: registered under. The bundle generator's ``FrameworkResolver`` performs the
#: same aliasing before writing ``established_articles``; this table lets a
#: caller who reads an un-resolved ``article_id`` still find the template.
_FRAMEWORK_ALIASES: dict[str, str] = {
    # The vault spells the Chilean Penal Code two ways: ``CP`` in older
    # violations and ``CHIPENCOD`` in newer ones (after the chip-encoding
    # section was merged into the same corpus file). The registry's canonical
    # code is ``CPCL``.
    "CP": "CPCL",
    "CHIPENCOD": "CPCL",
}


# ---------------------------------------------------------------------------
# Lookup and parsing
# ---------------------------------------------------------------------------

#: ``...Art.<number>[.<numeral>].elem.<key>``. Anchored at the tail so a
#: hierarchy segment such as ``T4.C3`` in the article prefix cannot be
#: mistaken for a numeral.
_ELEMENT_TAIL_RE = re.compile(
    r"^(?P<article>.+?\.Art\.[A-Za-z0-9_]+)"
    r"(?:\.(?P<numeral>[A-Za-z0-9_]+))?"
    r"\.elem\.(?P<key>[a-z_][a-z0-9_]*)$"
)


def parse_element_id(element_id: str) -> tuple[str, str | None, str] | None:
    """Split ``<article>.<numeral>.elem.<key>`` into its three parts.

    Returns ``None`` when the string is not shaped like an element id — the
    caller decides whether that is a defect (V21 says yes) or simply an
    uncanonical id from a bundle the template registry does not know about.

    Examples::

        parse_element_id("CL.CHIPENCOD.T4.C3.Art.193.8.elem.modalidad_ocultacion")
        # -> ("CL.CHIPENCOD.T4.C3.Art.193", "8", "modalidad_ocultacion")

        parse_element_id("CL.CPCL.C1.Art.255.elem.vejacion_injusta")
        # -> ("CL.CPCL.C1.Art.255", None, "vejacion_injusta")
    """
    match = _ELEMENT_TAIL_RE.match(element_id)
    if match is None:
        return None
    return match.group("article"), match.group("numeral"), match.group("key")


def split_article_id(article_id: str) -> tuple[str, str] | None:
    """``CL.CHIPENCOD.T4.C3.Art.193`` → ``("CHIPENCOD", "193")``.

    The framework segment is whatever sits between the jurisdiction and the
    optional hierarchy segments; the article number is the single token after
    ``Art.``. Both are needed for a lookup that does not depend on how the
    caller happens to spell the hierarchy.

    Returns ``None`` when the string is not shaped like an article id — the
    caller treats a miss as "no canonicalization available", never as a
    rejection.
    """
    parts = article_id.split(".")
    if len(parts) < 3 or not parts[0]:
        return None
    try:
        marker = parts.index("Art")
    except ValueError:
        return None
    if marker < 2 or marker + 1 >= len(parts):
        return None
    return parts[1], parts[marker + 1]


def _framework_candidates(framework: str) -> list[str]:
    """The framework codes worth trying for a template lookup.

    The one given, its alias, and any framework that aliases to it — so a
    template registered under ``CPCL`` is found from an ``article_id`` that
    says ``CHIPENCOD``, and vice versa. Order is preserved and de-duplicated
    so the first hit wins deterministically.
    """
    candidates = [framework]
    aliased = _FRAMEWORK_ALIASES.get(framework)
    if aliased and aliased not in candidates:
        candidates.append(aliased)
    for src, dst in _FRAMEWORK_ALIASES.items():
        if dst == framework and src not in candidates:
            candidates.append(src)
    return candidates


def find_template(
    article_id: str, numeral: str | None = None
) -> ArticleTemplate | None:
    """Look up the template for an article, or ``None`` when it has none.

    Tries the exact ``(framework, number, numeral)`` first, then the
    numeral-less form, then the ``numeral=None`` fallback described in the
    module docstring. A miss is not an error: it means the enrichment stage
    will fall back to free-form decomposition for this article.
    """
    split = split_article_id(article_id)
    if split is None:
        return None
    framework, number = split
    frameworks = _framework_candidates(framework)

    numerals = (numeral, None) if numeral is not None else (None,)
    for fw in frameworks:
        for num in numerals:
            template = TEMPLATES.get((fw, number, num))
            if template is not None:
                return template

    # Numeral-less fallback: when the caller supplied no numeral and exactly
    # one registration exists for (framework, number), use it. See the module
    # docstring for why this is safe and what it covers.
    if numeral is None:
        matches = [
            t for k, t in TEMPLATES.items()
            if k[1] == number and k[0] in frameworks
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def iter_templates() -> Iterator[ArticleTemplate]:
    return iter(TEMPLATES.values())


# ---------------------------------------------------------------------------
# Conformance helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateDrift:
    """The difference between a grid's element keys and its template's."""
    article_id: str
    missing_required: tuple[str, ...]
    extra_keys: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not self.missing_required and not self.extra_keys

    def reason(self) -> str:
        parts: list[str] = []
        if self.missing_required:
            parts.append(f"missing required: {list(self.missing_required)}")
        if self.extra_keys:
            parts.append(f"extra keys: {list(self.extra_keys)}")
        return "; ".join(parts) if parts else "conforms"


def template_drift(
    article_id: str, element_keys: Iterable[str]
) -> TemplateDrift | None:
    """Return the drift of ``element_keys`` from the article's template.

    Returns ``None`` when the article has no template — "cannot judge" must
    not be reported as "conforms", because a caller that treats them the same
    will stop noticing when a template is removed.
    """
    template = find_template(article_id)
    if template is None:
        return None
    present = set(element_keys)
    return TemplateDrift(
        article_id=article_id,
        missing_required=tuple(sorted(template.required_keys() - present)),
        extra_keys=tuple(sorted(present - template.keys())),
    )


def canonicalize_element_ids(
    grid: "ArticleElementGrid",
    canonical_article_id: str | None = None,
) -> "ArticleElementGrid":
    """Rewrite ``grid.elements[].element_id`` to a canonical spelling.

    For a grid whose element keys already match a template but whose ids are
    spelled inconsistently — a numeral missing, a hierarchy segment dropped —
    this returns a copy with the ids the template would compose. It is a
    **naming** operation only: it does not touch proof_status, evidence
    segments, or arguments.

    ``canonical_article_id`` is the prefix the caller wants the element ids to
    use. Defaults to ``grid.article_id`` — which is the right choice for a
    bundle that already carries the spelling it wants.

    Refuses when the grid carries any key the template does not know: a grid
    that has been extended for an article-specific reason is not one this
    helper can safely rewrite, because it has no way to compose an id for the
    extra element. Returns ``grid`` unchanged in that case, and also when the
    article has no template at all.
    """
    article_id = canonical_article_id or grid.article_id
    template = find_template(article_id)
    if template is None:
        return grid
    allowed = template.element_ids(article_id)
    rewrites: dict[str, str] = {}
    for el in grid.elements:
        parsed = parse_element_id(el.element_id)
        if parsed is None:
            continue
        _article, _numeral, key = parsed
        if key not in allowed:
            return grid
        rewrites[el.element_id] = allowed[key]

    if not rewrites:
        return grid
    new_elements = [
        el.model_copy(update={"element_id": rewrites[el.element_id]})
        if el.element_id in rewrites else el
        for el in grid.elements
    ]
    return grid.model_copy(update={"elements": new_elements})