"""Calculation rules (§1.3 / PRD §3.4, §3.8, §3.9, §2.6)."""

import math
from decimal import Decimal, ROUND_HALF_UP

from core import half_up, dec_out, round_half_up_int, ceil_int, floor_int, floor_zero

BUBBLE_UP_FLOOR = Decimal("0.05")
DISCREPANCY_POINTS = 15
VOLUME_TIER_BOUNDARIES = [0, 10000, 50000]
VOLUME_TIER_RATES_CENTS = [18, 14, 9]
FIXED_OVERAGE_FEE_CENTS = 250
MIXTURE_SCALE = Decimal(1000000)
MILLI = Decimal(1000)
PPM_SCALE = Decimal(1000000)


def D(value):
    """Coerce ints/floats/Decimals to an exact Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# -----------------------------------------------------------------------------
# score_effective_and_odds
# -----------------------------------------------------------------------------
def effective_score(model, variant, raw_posted_score):
    """Band resolved first, clamp applied, penalty then taken from the clamped value."""
    diff = Decimal(raw_posted_score - variant["ref_score"])
    band = int(floor_zero(diff / D(variant["segment_width"])))
    band = min(max(band, 0), 2)
    provisional = raw_posted_score + variant["segment_offsets"][band]
    provisional = min(max(provisional, model["score_floor"]), model["score_ceiling"])
    rounding_penalty = ceil_int(D(provisional) * D(variant["rounding_penalty_pct"]))
    return provisional - rounding_penalty


def odds_at_posted_score(variant, effective):
    """PRD §3.8: "The odds at the effective score are the variant's `base_odds`
    multiplied by two raised to the power of the effective score minus the anchor,
    all divided by the variant's `double_odds_points`. That figure is combined
    with a cut-off companion term of one plus the variant's `elongation_points`
    divided by the effective score, and the sum is rounded half-up to four decimal
    places to become `odds_at_posted_score`."

    Note: the exponent is "effective score minus the anchor" divided by
    `double_odds_points`, rounded half-up to four places.
    """
    ratio = (Decimal(effective - variant["ref_score"])) / D(variant["double_odds_points"])
    odds_at_effective = D(variant["base_odds"]) * (Decimal(2) ** ratio)
    return half_up(odds_at_effective, 4)


# -----------------------------------------------------------------------------
# license_marginal_fee
# -----------------------------------------------------------------------------
def fee_through(n):
    total = 0
    for i, lower in enumerate(VOLUME_TIER_BOUNDARIES):
        upper = VOLUME_TIER_BOUNDARIES[i + 1] if i + 1 < len(VOLUME_TIER_BOUNDARIES) else None
        if n > lower:
            top = n if upper is None else min(n, upper)
            total += (top - lower) * VOLUME_TIER_RATES_CENTS[i]
    return total


def marginal_fee_cents(cumulative_count_before, entitled_count):
    cb = cumulative_count_before
    marginal = fee_through(cb + 1) - fee_through(cb)
    if cb + 1 > entitled_count:
        marginal += FIXED_OVERAGE_FEE_CENTS
    return marginal


def blended_fee_cents(prospective_count):
    """Highest tier reached applied against every unit; reporting only."""
    if prospective_count <= 0:
        return 0
    rate = VOLUME_TIER_RATES_CENTS[0]
    for i, lower in enumerate(VOLUME_TIER_BOUNDARIES):
        upper = VOLUME_TIER_BOUNDARIES[i + 1] if i + 1 < len(VOLUME_TIER_BOUNDARIES) else None
        if prospective_count > lower:
            rate = VOLUME_TIER_RATES_CENTS[i]
    return prospective_count * rate


def tier_index(prospective_count):
    idx = 0
    for i, lower in enumerate(VOLUME_TIER_BOUNDARIES):
        if prospective_count > lower:
            idx = i
    return idx


# -----------------------------------------------------------------------------
# cutoff_recalibration
# -----------------------------------------------------------------------------
def cutoff_recalibration(source_variant, source_model, target_variant, target_model, old_cutoff_score):
    floor = target_model["score_floor"]
    ceiling = target_model["score_ceiling"]

    score_preserving = old_cutoff_score + (target_variant["ref_score"] - source_variant["ref_score"])
    score_preserving = min(max(score_preserving, floor), ceiling)

    odds_at_old = D(source_variant["base_odds"]) * (
        Decimal(2) ** (Decimal(old_cutoff_score - source_variant["ref_score"]) / D(source_variant["double_odds_points"]))
    )
    implied_point_shift = D(target_variant["double_odds_points"]) * (
        (odds_at_old / D(target_variant["base_odds"])).log10() / Decimal(2).log10()
    )
    odds_preserving = round_half_up_int(D(target_variant["ref_score"]) + implied_point_shift)
    odds_preserving = min(max(odds_preserving, floor), ceiling)

    return {
        "new_cutoff_score_preserving": score_preserving,
        "new_cutoff_odds_preserving": odds_preserving,
        "cutoff_disagreement_points": score_preserving - odds_preserving,
    }


# -----------------------------------------------------------------------------
# composite_score
# -----------------------------------------------------------------------------
def composite_scores(postings):
    """postings: list of dicts carrying effective_score and variant_weight_pct."""
    count = len(postings)
    if count == 0:
        return {"weighted_composite": 0.0, "unweighted_composite": 0.0, "reconciliation_variance": 0.0}

    weighted = Decimal(0)
    for posting in postings:
        product = D(posting["effective_score"]) * D(posting["variant_weight_pct"])
        weighted += half_up(product, 2)
    weighted = half_up(weighted, 2)

    score_sum = sum(p["effective_score"] for p in postings)
    mean = Decimal(score_sum) / Decimal(count)
    truncated = Decimal(floor_int(mean * Decimal(100))) / Decimal(100)
    unweighted = half_up(truncated, 2)

    variance = half_up(abs(weighted - unweighted), 2)
    return {
        "weighted_composite": dec_out(weighted, 2),
        "unweighted_composite": dec_out(unweighted, 2),
        "reconciliation_variance": dec_out(variance, 2),
    }


# -----------------------------------------------------------------------------
# composite_reason_code (bubble-up)
# -----------------------------------------------------------------------------
def composite_code_for(variant, model, trigger_feature_code, depth_tier):
    return f"{model['version_label']}-{variant['industry']}-{trigger_feature_code}-{depth_tier}"


def weight_effective(weight_pct, weight_received_pct):
    return half_up(D(weight_pct) + D(weight_received_pct), 4)


def bubble_up(child_reason_codes):
    """Sum of weights of qualifying children (weight_pct < BUBBLE_UP_FLOOR).

    One hop only: only the immediate parent receives the share, so the caller
    is responsible for passing only direct children of the node being updated.
    """
    total = Decimal(0)
    for child in child_reason_codes:
        if D(child["weight_pct"]) < BUBBLE_UP_FLOOR:
            total += D(child["weight_pct"])
    return half_up(total, 4)


# -----------------------------------------------------------------------------
# migration_window_ratio
# -----------------------------------------------------------------------------
def window_outcome_mixture_ratio_ppm(score_sum, cumulative_score_count):
    if cumulative_score_count == 0:
        return 0
    ratio = (Decimal(score_sum) * MIXTURE_SCALE) / (MILLI * Decimal(cumulative_score_count))
    return round_half_up_int(ratio)


# -----------------------------------------------------------------------------
# disparate_impact_ratio
# -----------------------------------------------------------------------------
def disparate_impact_ratio_ppm(group_counts):
    """group_counts: {True: (approve, decline), False: (approve, decline)}"""
    def rate(group):
        approve, decline = group
        total = approve + decline
        if total == 0:
            return Decimal(0)
        return Decimal(approve) / Decimal(total)

    p25 = rate(group_counts.get(True, (0, 0)))
    p75 = rate(group_counts.get(False, (0, 0)))
    if p75 == 0:
        return 0
    return round_half_up_int((p25 / p75) * PPM_SCALE)


# -----------------------------------------------------------------------------
# model_cascade_depth
# -----------------------------------------------------------------------------
def cascade_depth(model):
    depth = 0
    seen = {model["id"]}
    pred = model.get("predecessor_model_id")
    while pred:
        if pred in seen:
            break
        seen.add(pred)
        depth += 1
        node = None
        from core import DB
        node = DB["score_models"].get(pred)
        if node is None:
            break
        pred = node.get("predecessor_model_id")
    return depth


# -----------------------------------------------------------------------------
# bureau_discrepancy_scan
# -----------------------------------------------------------------------------
def bureau_discrepancy_scan(poster, peers):
    """peers: list of ScoreResult dicts (excluding the poster) sorted per §3.4.

    PRD §3.4: the spread is over every peer; a peer is *flagged* when its
    effective score differs from the poster's by at least 15 points, and the
    response carries the poster's own score, the spread, the count of flagged
    peers, and the list of peer bureau codes.
    """
    if peers:
        peer_spread = max(p["effective_score"] for p in peers) - min(p["effective_score"] for p in peers)
    else:
        peer_spread = 0
    flagged = [p for p in peers if abs(p["effective_score"] - poster["effective_score"]) >= DISCREPANCY_POINTS]
    return {
        "poster_effective_score": poster["effective_score"],
        "peer_spread": peer_spread,
        "flagged_peer_count": len(flagged),
        "peer_bureau_codes": [p["bureau_code"] for p in peers],
    }