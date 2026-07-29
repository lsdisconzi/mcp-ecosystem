"""Confidence derivation.

The whole point of putting this in a dedicated module is that the formula
should be auditable. The previous bundle had a 0.99 confidence in one place
and the prose admitted it was hand-picked. That's the failure mode this
module exists to prevent.

The formula is intentionally simple — a weighted mean of element grids,
scaled by the fraction of authorities that have been verified. As the
project matures (Qdrant similarity over jurisprudence to find supporting
authorities; Neo4j cross-reference propagation; etc.) the formula can
evolve here without touching anything else.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import ConfidenceDerivation, Violation


# Per-article weights for the weighted mean. Today this is configured at the
# call site; tomorrow it could be inferred from the applicability field
# ('direct' vs 'indirect_predicate' vs 'supporting').
DEFAULT_APPLICABILITY_WEIGHTS: dict[str, float] = {
    "direct": 1.0,
    "indirect_predicate": 0.33,
    "supporting": 0.2,
}


def derive_confidence(
    violation: Violation,
    article_weights: dict[str, float] | None = None,
    authority_verification_floor: float = 0.85,
) -> ConfidenceDerivation:
    """Compute a confidence value from the element grids and authorities.

    Returns a ConfidenceDerivation that is fully self-describing — the
    formula, components, and verification factor are all recorded.
    """
    grids_by_article = {g.article_id: g for g in violation.element_grids}
    if not grids_by_article:
        return ConfidenceDerivation(
            value=0.0,
            components={},
            authorities_verification_factor=0.0,
            derivation_formula="no element grids; confidence undefined",
            derived_at=datetime.now(timezone.utc),
        )

    # Default weights: derive from each article's applicability.
    if article_weights is None:
        article_weights = {}
        for article in violation.established_articles:
            article_weights[article.article_id] = DEFAULT_APPLICABILITY_WEIGHTS.get(
                article.applicability, 0.5
            )
        # Anything in grids but not in established_articles gets default 1.0
        # (covers single-article cases where the user didn't configure weights).
        for aid in grids_by_article:
            article_weights.setdefault(aid, 1.0)

    components: dict[str, float] = {}
    weighted_sum = 0.0
    weight_total = 0.0
    for article_id, grid in grids_by_article.items():
        w = article_weights.get(article_id, 0.0)
        if w == 0.0:
            continue
        score = grid.weighted_score()
        components[article_id] = round(score, 3)
        weighted_sum += w * score
        weight_total += w
    base = weighted_sum / weight_total if weight_total > 0 else 0.0

    # Authorities verification factor: 1.0 if all verified, floor configurable
    # via the authority_verification_floor parameter (default 0.85) to avoid
    # harshly penalising bundles where authorities just haven't been
    # researched yet.
    if violation.authorities:
        verified = sum(1 for a in violation.authorities if a.verified)
        ratio = verified / len(violation.authorities)
        verification_factor = authority_verification_floor + (1.0 - authority_verification_floor) * ratio
    else:
        # No authorities listed at all: same as "all unverified".
        verification_factor = authority_verification_floor

    final = round(base * verification_factor, 2)

    formula = (
        "value = round( "
        "sum_per_article( applicability_weight × element_grid.weighted_score ) "
        "/ sum_of_weights × authorities_verification_factor, 2 )"
        f"; authorities_verification_factor = {authority_verification_floor} + "
        f"{1.0 - authority_verification_floor:.2f} × verified_ratio = {verification_factor:.3f}"
    )

    return ConfidenceDerivation(
        value=final,
        components=components,
        authorities_verification_factor=round(verification_factor, 3),
        derivation_formula=formula,
        derived_at=datetime.now(timezone.utc),
    )


def attach_confidence(violation: Violation) -> Violation:
    """Convenience: derive confidence and attach it to the violation,
    preserving prior values in the history list."""
    new_conf = derive_confidence(violation)
    history = []
    if violation.confidence is not None:
        history = list(violation.confidence.history) + [
            f"{violation.confidence.derived_at.isoformat()}: value={violation.confidence.value}"
        ]
    new_conf = new_conf.model_copy(update={"history": history})
    return violation.model_copy(update={"confidence": new_conf})
