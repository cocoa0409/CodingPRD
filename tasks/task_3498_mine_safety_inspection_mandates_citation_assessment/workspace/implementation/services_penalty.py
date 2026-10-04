"""Penalty points and the penalty dollar pipeline (PRD section 3.4).

Pipeline order is PINNED: (1) marginal tier dollars, (2) repeat multiplier with
round-half-up to whole cents, (3) good-faith 10% discount with round-half-up
(final variant only), (4) statutory floor applied LAST. Integer cents only;
intermediate values are exact Decimals.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from constants import (
    FLOOR_CITATION_CENTS,
    FLOOR_CITATION_SS_CENTS,
    FLOOR_ORDER_CENTS,
    GOOD_FAITH_RATE,
    HISTORY_BANDS,
    HISTORY_WINDOW_DAYS,
    LIKELIHOOD_POINTS,
    NEGLIGENCE_POINTS,
    REPEAT_MULTIPLIER,
    SEVERITY_POINTS,
    SIZE_BANDS,
    SS_SURCHARGE,
    TIER1_CENTS,
    TIER1_POINT_CAP,
    TIER2_CENTS,
    TIER2_POINT_CAP,
    TIER3_CENTS,
    TIER3_POINT_CAP,
    TIER4_CENTS,
)


def persons_points(persons_affected):
    if persons_affected <= 1:
        return 0
    if persons_affected <= 5:
        return 5
    if persons_affected <= 20:
        return 10
    return 20


def history_points(count):
    for minimum, points in HISTORY_BANDS:
        if count >= minimum:
            return points
    return 0


def size_points(annual_tonnage_tons):
    for minimum, points in SIZE_BANDS:
        if annual_tonnage_tons >= minimum:
            return points
    return 0


def compute_points_total(citation):
    """Sum of the seven additive factor tables for a (new) citation.

    The citation dict must carry its factor fields plus mine_id and issued_at,
    and must NOT yet be in the store (the new citation is excluded from its own
    history count). History counts the mine's other non-VACATED citations whose
    issued_at falls in (issued_at - 730 days, issued_at].
    """
    total = NEGLIGENCE_POINTS[citation["negligence"]]
    total += LIKELIHOOD_POINTS[citation["gravity_likelihood"]]
    total += SEVERITY_POINTS[citation["gravity_severity"]]
    total += persons_points(citation["persons_affected"])
    if citation["significant_and_substantial"]:
        total += SS_SURCHARGE
    issued_at = citation["issued_at"]
    window_start = issued_at - timedelta(days=HISTORY_WINDOW_DAYS)
    prior = 0
    for other in store.citations.values():
        if other["mine_id"] != citation["mine_id"]:
            continue
        if other["id"] == citation.get("id"):
            continue
        if other["contest_status"] == "VACATED":
            continue
        if window_start < other["issued_at"] <= issued_at:
            prior += 1
    total += history_points(prior)
    mine = store.mines.get(citation["mine_id"])
    operator = store.operators.get(mine["operator_id"]) if mine else None
    total += size_points(operator["annual_tonnage_tons"] if operator else 0)
    return total


def tiered_gross_cents(points):
    tier1 = min(points, TIER1_POINT_CAP) * TIER1_CENTS
    tier2 = min(max(points - TIER1_POINT_CAP, 0), TIER2_POINT_CAP) * TIER2_CENTS
    tier3 = min(max(points - TIER1_POINT_CAP - TIER2_POINT_CAP, 0), TIER3_POINT_CAP) * TIER3_CENTS
    tier4 = max(points - TIER1_POINT_CAP - TIER2_POINT_CAP - TIER3_POINT_CAP, 0) * TIER4_CENTS
    return tier1 + tier2 + tier3 + tier4


def floor_cents_for(kind, significant_and_substantial):
    if kind == "ORDER":
        return FLOOR_ORDER_CENTS
    if significant_and_substantial:
        return FLOOR_CITATION_SS_CENTS
    return FLOOR_CITATION_CENTS


def _round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def run_pipeline(points_total, kind, significant_and_substantial, repeat_violation, good_faith):
    """Returns (amount_cents, statutory_floor_applied)."""
    gross = tiered_gross_cents(points_total)
    if repeat_violation:
        multiplied = _round_half_up_cents(Decimal(gross) * REPEAT_MULTIPLIER)
    else:
        multiplied = gross
    if good_faith:
        discount = _round_half_up_cents(Decimal(multiplied) * GOOD_FAITH_RATE)
        net = multiplied - discount
    else:
        net = multiplied
    floor = floor_cents_for(kind, significant_and_substantial)
    return max(net, floor), floor > net


def create_assessment(citation, points_total):
    """Proposed variant at issuance: pipeline steps 1, 2, 4 (no good faith)."""
    proposed, floor_applied = run_pipeline(
        points_total,
        citation["kind"],
        citation["significant_and_substantial"],
        citation["repeat_violation"],
        False,
    )
    return store.new_entity(store.assessments, {
        "citation_id": citation["id"],
        "points_total": points_total,
        "proposed_penalty_cents": proposed,
        "final_penalty_cents": None,
        "good_faith_applied": False,
        "statutory_floor_applied": floor_applied,
        "status": "PROPOSED",
    })


def good_faith_eligible(citation):
    return (
        citation["abatement_status"] == "VERIFIED"
        and citation["verified_at"] is not None
        and citation["verified_at"] <= citation["abatement_deadline"]
    )


def apply_final_variant(assessment, citation):
    """Final variant (window lapse or AFFIRMED): steps 1-4 with good faith when
    the citation was VERIFIED with verified_at on or before the deadline."""
    good_faith = good_faith_eligible(citation)
    amount, floor_applied = run_pipeline(
        assessment["points_total"],
        citation["kind"],
        citation["significant_and_substantial"],
        citation["repeat_violation"],
        good_faith,
    )
    assessment["final_penalty_cents"] = amount
    # The stored figure reflects the discount only when the floor did not
    # overwrite the discounted net (PRD 3.4: "whether a stored final figure
    # reflects the discount").
    assessment["good_faith_applied"] = bool(good_faith and not floor_applied)
    assessment["statutory_floor_applied"] = floor_applied
    assessment["status"] = "FINAL"


def apply_modified_outcome(assessment, citation, modified_penalty_cents):
    """MODIFIED: max(modified_penalty_cents, floor); good faith never applied."""
    floor = floor_cents_for(citation["kind"], citation["significant_and_substantial"])
    assessment["final_penalty_cents"] = max(modified_penalty_cents, floor)
    assessment["good_faith_applied"] = False
    assessment["statutory_floor_applied"] = floor > modified_penalty_cents
    assessment["status"] = "FINAL"


def apply_vacated_outcome(assessment):
    """VACATED: final of zero cents; the floor is not applied."""
    assessment["final_penalty_cents"] = 0
    assessment["good_faith_applied"] = False
    assessment["statutory_floor_applied"] = False
    assessment["status"] = "FINAL"


def assessment_for(citation_id):
    for assessment in store.assessments.values():
        if assessment["citation_id"] == citation_id:
            return assessment
    return None
