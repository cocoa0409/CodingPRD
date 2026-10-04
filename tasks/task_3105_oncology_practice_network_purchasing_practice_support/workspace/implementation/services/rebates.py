"""Rebate programs, qualifications, compliance scoring and market share.

The compliance score is a weighted mean over exactly three registered score
keys; a zero weight removes its component from BOTH numerator and denominator.
The rebate amount is pinned to rounding ORDER B (sum then round) and reaches the
final variant once the period sits strictly behind the network's epoch.
"""

from decimal import Decimal

import db
from services import helpers
from services import pricing
from utils import half_up, num, parse_iso, ratio4

COMPACT_DISCOUNT_RATE = Decimal("0.0")
REBATE_CAP_PER_PRACTICE_CENTS = 2500000
DUAL_VARIANT_RECONCILIATION_FEE_CENTS = 0

SCORE_KEYS = ("reporting_timeliness", "pathway_adherence", "price_transparency")
WEIGHT_KEYS = {
    "reporting_timeliness": "weight_reporting_compliance",
    "pathway_adherence": "weight_adherence_steering",
    "price_transparency": "weight_transparency",
}


def epoch_window_for(network, period_epoch_index):
    return helpers.epoch_window(network, period_epoch_index)


def reporting_timeliness(qualification, network):
    """1.0 on or before the epoch close; 0.5 inside the grace window; 0.0 when
    the report was never submitted."""
    submitted_at = parse_iso(qualification.get("compliance_report_submitted_at"))
    if submitted_at is None:
        return Decimal(0)
    closed_at = helpers.epoch_closed_at(network, qualification.get("period_epoch_index"))
    if submitted_at <= closed_at:
        return Decimal(1)
    return Decimal("0.5")


def compute_compliance_score(qualification, practice, program, network):
    scores = {
        "reporting_timeliness": reporting_timeliness(qualification, network),
        "pathway_adherence": num(practice.get("pathway_adherence_pct")) or Decimal(0),
        "price_transparency": helpers.price_transparency_score(practice["id"]),
    }
    weights = {}
    for key, weight_key in WEIGHT_KEYS.items():
        weight = num(program.get(weight_key))
        weights[key] = int(weight) if weight is not None else 1

    numerator = Decimal(0)
    denominator = 0
    for key in SCORE_KEYS:
        weight = weights[key]
        if weight == 0:
            continue
        numerator += scores[key] * Decimal(weight)
        denominator += weight
    if denominator == 0:
        return 0.0
    return ratio4(numerator / Decimal(denominator))


def compact_discount_credit(compliance_score):
    return half_up(Decimal(str(compliance_score)) * COMPACT_DISCOUNT_RATE * Decimal(10000))


def market_share(qualification, practice, program):
    window = epoch_window_for(
        db.get("networks", practice["network_id"]), qualification.get("period_epoch_index")
    )
    denominator, rider = pricing.routing_denominator(practice, window)
    provisional, final, fallback = pricing.spend_variants(
        practice["id"], program.get("drug_ndc_scope") or "ALL", window
    )
    if denominator == 0:
        return 0.0
    return ratio4(Decimal(provisional) / Decimal(denominator))


def is_qualified(market_share_pct, compliance_score, program):
    """Both comparisons are inclusive."""
    share_threshold = num(program.get("market_share_threshold_pct")) or Decimal(0)
    score_threshold = num(program.get("compliance_min_score")) or Decimal(0)
    return (
        Decimal(str(market_share_pct)) >= share_threshold
        and Decimal(str(compliance_score)) >= score_threshold
    )


def rebate_amount(qualification, practice, program, network):
    """ORDER B: multiply each order's extended cost by the rebate rate, sum the
    exact products, and round the sum once. Cap applied after rounding."""
    window = epoch_window_for(network, qualification.get("period_epoch_index"))
    provisional_spend, final_spend, fallback_spend = pricing.spend_variants(
        practice["id"], program.get("drug_ndc_scope") or "ALL", window
    )
    rate = num(program.get("rebate_pct")) or Decimal(0)

    provisional_amount = half_up(Decimal(provisional_spend) * rate)
    if provisional_amount > REBATE_CAP_PER_PRACTICE_CENTS:
        provisional_amount = REBATE_CAP_PER_PRACTICE_CENTS

    period = int(qualification.get("period_epoch_index") or 0)
    current = int(network.get("allocation_epoch_index") or 0)
    if period >= current:
        return provisional_amount, "provisional"

    credit = int(qualification.get("compact_discount_credit_cents") or 0)
    final = (
        provisional_amount
        - half_up(Decimal(fallback_spend) * rate)
        - credit
        - DUAL_VARIANT_RECONCILIATION_FEE_CENTS
    )
    if final < 0:
        return 0, "disqualified"
    return final, "final"


def refresh_qualification(qualification):
    """Recompute the qualification's computed fields in place."""
    practice = db.get("practices", qualification["practice_id"])
    program = db.get("rebate_programs", qualification["rebate_program_id"])
    if practice is None or program is None:
        return qualification
    network = db.get("networks", practice["network_id"])
    qualification["market_share_pct"] = market_share(qualification, practice, program)
    qualification["compliance_score"] = compute_compliance_score(
        qualification, practice, program, network
    )
    qualification["compact_discount_credit_cents"] = compact_discount_credit(
        qualification["compliance_score"]
    )
    qualified = is_qualified(
        qualification["market_share_pct"], qualification["compliance_score"], program
    )
    qualification["_qualified_test"] = qualified
    amount, variant = rebate_amount(qualification, practice, program, network)
    if variant == "disqualified":
        amount = 0
    qualification["rebate_amount_cents"] = amount
    return qualification


def qualified_test(qualification):
    """Whether the qualification's own inclusive thresholds are met."""
    practice = db.get("practices", qualification["practice_id"])
    program = db.get("rebate_programs", qualification["rebate_program_id"])
    if practice is None or program is None:
        return False
    return is_qualified(
        qualification.get("market_share_pct", 0),
        qualification.get("compliance_score", 0),
        program,
    )


def mark_practice_mirror(practice):
    """Practice.is_rebate_qualified mirrors the current-epoch qualification."""
    rows = db.where("rebate_qualifications", practice_id=practice["id"])
    current = int((db.get("networks", practice["network_id"]) or {}).get("allocation_epoch_index") or 0)
    mirror = False
    for qualification in rows:
        if int(qualification.get("period_epoch_index") or 0) != current:
            continue
        if qualification["status"] in ("QUALIFIED", "PAID"):
            mirror = True
        elif qualification["status"] == "PENDING" and qualified_test(qualification):
            mirror = True
    practice["is_rebate_qualified"] = mirror
    return mirror


def recompute_mirror_for(practice):
    return mark_practice_mirror(practice)