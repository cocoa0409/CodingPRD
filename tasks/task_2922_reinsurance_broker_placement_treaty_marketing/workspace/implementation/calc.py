"""The ten calculation rules of PRD section 3, implemented literally.

Every constant below is quoted from the PRD; nothing here reads a wall clock and
nothing here uses binary floating point.
"""
from decimal import Decimal
from fractions import Fraction

from util import (
    HUNDRED,
    Q4,
    ceil_div,
    dec,
    floor_4dp,
    frac,
    money,
    pct4,
    round_half_up,
    score2,
)

# --- constants -------------------------------------------------------------
REINSTATEMENT_RATE_LOAD_PCT = Decimal("5.0000")

VOLUME_DISCOUNT_TIERS = (
    (5000000, Decimal("0.0000")),
    (25000000, Decimal("2.5000")),
    (100000000, Decimal("5.0000")),
)
VOLUME_DISCOUNT_TOP_PCT = Decimal("7.5000")

SIGNOFF_MIN_SCORE = Decimal("70.00")
WEIGHT_DATA_QUALITY = Decimal("40")
WEIGHT_HISTORY = Decimal("25")
WEIGHT_LOSS_COMPLETENESS = Decimal("25")
WEIGHT_ACTUARIAL_REPORT = Decimal("10")
HISTORY_TARGET_YEARS = 5

SLIDE_PIVOT_LOSS_RATIO_PCT = Decimal("60.0000")
SLIDE_FACTOR = Decimal("0.5")
SLIDE_FLOOR_PCT = Decimal("20.0000")
SLIDE_CAP_PCT = Decimal("35.0000")

ARBITRATION_COST_PCT = Decimal("1.5")

CERTAINTY_WINDOW_DAYS = 30
CAPACITY_WINDOW_DAYS = 30
MAX_NEGOTIATION_ROUNDS = 3

FULL_PLACEMENT_PCT = Decimal("100.0000")


# ---------------------------------------------------------------------------
# 1. layer_technical_premium
# ---------------------------------------------------------------------------

def loaded_rate_pct(base_rate_pct, reinstatements_total):
    """base rate grossed up by five percent of itself per reinstatement.

    The loaded rate is carried unrounded into the premium step.
    """
    load = REINSTATEMENT_RATE_LOAD_PCT * dec(reinstatements_total)
    return dec(base_rate_pct) * (Decimal(1) + load / HUNDRED)


def volume_discount_pct(provisional_minor):
    for ceiling, pct in VOLUME_DISCOUNT_TIERS:
        if provisional_minor < ceiling:
            return pct
    return VOLUME_DISCOUNT_TOP_PCT


def layer_technical_premium(subject_premium_base_minor, base_rate_pct,
                            reinstatements_total):
    """Returns (provisional_minor, discount_pct, quoted_gross_premium_minor)."""
    rate = loaded_rate_pct(base_rate_pct, reinstatements_total)
    provisional = money(frac(subject_premium_base_minor) * frac(rate) / 100)
    discount = volume_discount_pct(provisional)
    quoted = money(frac(provisional) * (1 - frac(discount) / 100))
    return provisional, discount, quoted


# ---------------------------------------------------------------------------
# 2. signing_down_allocation
# ---------------------------------------------------------------------------

def signing_down_allocation(entries, method):
    """Allocate signed lines so the layer closes at exactly 100.0000.

    `entries` is an ordered list (created_at ASC) of dicts carrying:
        id, written (Decimal), is_lead (bool), reinsurer_name (str),
        created_at, seq
    Returns {id: Decimal signed_line_pct}.
    """
    if not entries:
        return {}

    lead = None
    if method == "LEAD_PROTECTED":
        for entry in entries:
            if entry["is_lead"]:
                lead = entry
                break

    result = {}
    if lead is not None:
        result[lead["id"]] = pct4(lead["written"])
        followers = [e for e in entries if e["id"] != lead["id"]]
        target = frac(FULL_PLACEMENT_PCT) - frac(lead["written"])
    else:
        followers = list(entries)
        target = frac(FULL_PLACEMENT_PCT)

    written_total = sum((frac(e["written"]) for e in followers), Fraction(0))
    if not followers or written_total == 0 or target <= 0:
        for entry in followers:
            result[entry["id"]] = Decimal("0.0000")
        return result

    floors = {}
    dropped = {}
    for entry in followers:
        raw = frac(entry["written"]) * target / written_total
        floor = floor_4dp(raw)
        floors[entry["id"]] = floor
        dropped[entry["id"]] = raw - frac(floor)

    allotted = sum(floors.values(), Decimal("0"))
    residue = (dec(target) - allotted).quantize(Q4)
    steps = int((residue / Q4).to_integral_value())

    if steps > 0:
        order = sorted(
            followers,
            key=lambda e: (
                -dropped[e["id"]],
                -frac(e["written"]),
                e["created_at"],
                e["reinsurer_name"],
                e["seq"],
            ),
        )
        index = 0
        while steps > 0:
            entry = order[index % len(order)]
            floors[entry["id"]] = (floors[entry["id"]] + Q4).quantize(Q4)
            steps -= 1
            index += 1

    for entry in followers:
        result[entry["id"]] = floors[entry["id"]].quantize(Q4)
    return result


# ---------------------------------------------------------------------------
# 3. brokerage_and_net_remittance
# ---------------------------------------------------------------------------

def brokerage_and_net_remittance(layer_lines, brokerage_pct):
    """`layer_lines` is an ordered list of (quoted_gross_premium_minor,
    signed_line_pct) tuples, one per BOUND line on a BOUND layer, plus the
    per-layer premium totals.

    Returns (gross_written, brokerage_earned, net_remittance, residue).
    """
    brokerage = 0
    net = 0
    for premium_minor, signed_pct in layer_lines:
        line_gross = money(frac(premium_minor) * frac(signed_pct) / 100)
        line_brokerage = money(frac(line_gross) * frac(brokerage_pct) / 100)
        brokerage += line_brokerage
        net += line_gross - line_brokerage
    return brokerage, net


# ---------------------------------------------------------------------------
# 4. submission_completeness_score
# ---------------------------------------------------------------------------

def submission_completeness_score(records, flags, years, completeness_pct,
                                  report_attached):
    if records == 0:
        quality = Fraction(0)
    else:
        quality = Fraction(records - flags, records)
    history = Fraction(min(int(years), HISTORY_TARGET_YEARS), HISTORY_TARGET_YEARS)
    loss = frac(completeness_pct) / 100
    total = (
        frac(WEIGHT_DATA_QUALITY) * quality
        + frac(WEIGHT_HISTORY) * history
        + frac(WEIGHT_LOSS_COMPLETENESS) * loss
    )
    if report_attached:
        total += frac(WEIGHT_ACTUARIAL_REPORT)
    return score2(total)


# ---------------------------------------------------------------------------
# 5. ceding_commission_settlement
# ---------------------------------------------------------------------------

def provisional_ceding_commission(quoted_gross_premium_minor, ceding_commission_pct):
    return money(frac(quoted_gross_premium_minor) * frac(ceding_commission_pct) / 100)


def loss_ratio_pct(incurred_ceded_minor, quoted_gross_premium_minor):
    if not quoted_gross_premium_minor:
        return Decimal("0.0000")
    return pct4(Fraction(100) * frac(incurred_ceded_minor)
                / frac(quoted_gross_premium_minor))


def final_ceding_commission_pct(ceding_commission_pct, loss_ratio):
    """Slide, then clamp into the corridor, then round to four decimals."""
    raw = frac(ceding_commission_pct) + (
        (frac(SLIDE_PIVOT_LOSS_RATIO_PCT) - frac(loss_ratio)) * frac(SLIDE_FACTOR)
    )
    if raw < frac(SLIDE_FLOOR_PCT):
        raw = frac(SLIDE_FLOOR_PCT)
    elif raw > frac(SLIDE_CAP_PCT):
        raw = frac(SLIDE_CAP_PCT)
    return pct4(raw)


def final_ceding_commission(quoted_gross_premium_minor, final_pct):
    return money(frac(quoted_gross_premium_minor) * frac(final_pct) / 100)


# ---------------------------------------------------------------------------
# 6. claim_cession_waterfall
# ---------------------------------------------------------------------------

def subject_loss_minor(layer, gross_claim_minor):
    if layer["layer_type"] == "QUOTA_SHARE":
        return money(frac(gross_claim_minor) * frac(layer["cession_pct"]) / 100)
    return max(0, gross_claim_minor - layer["attachment_minor"])


def aggregate_available_minor(layer):
    ceiling = layer["limit_minor"] * (1 + layer["reinstatements_total"])
    return max(0, ceiling - layer["limit_eroded_minor"])


def ceded_claim_minor(layer, gross_claim_minor):
    subject = subject_loss_minor(layer, gross_claim_minor)
    event_cap = layer["sublimit_minor"] if layer["sublimit_minor"] > 0 else layer["limit_minor"]
    return min(subject, event_cap, layer["limit_minor"], aggregate_available_minor(layer))


def arbitration_cost_minor(ceded_minor, route):
    if route != "ARBITRATION":
        return 0
    return money(frac(ceded_minor) * frac(ARBITRATION_COST_PCT) / 100)


def erosion_after_collection(layer, collected_delta_minor):
    """Returns (new_eroded, new_reinstatements_used, reinstated_amount_minor)."""
    limit = layer["limit_minor"]
    previous_used = layer["reinstatements_used"]
    new_eroded = layer["limit_eroded_minor"] + collected_delta_minor
    if limit <= 0:
        return new_eroded, previous_used, 0
    new_used = max(0, ceil_div(new_eroded, limit) - 1)
    reinstated = new_eroded - limit * (1 + previous_used)
    if reinstated < 0:
        reinstated = 0
    return new_eroded, new_used, reinstated


def reinstatement_premium_minor(layer, reinstated_minor):
    if layer["limit_minor"] <= 0 or reinstated_minor <= 0:
        return 0
    return money(
        frac(layer["quoted_gross_premium_minor"])
        * frac(layer["reinstatement_premium_pct"]) / 100
        * Fraction(reinstated_minor, layer["limit_minor"])
    )


# ---------------------------------------------------------------------------
# 7. reinsurer_aggregate_capacity
# ---------------------------------------------------------------------------

def line_capacity_minor(limit_minor, effective_line_pct):
    return money(frac(limit_minor) * frac(effective_line_pct) / 100)


# ---------------------------------------------------------------------------
# 9. renewal_analytics
# ---------------------------------------------------------------------------

def rate_on_line_pct(gross_written_premium_minor, bound_limit_minor):
    if not bound_limit_minor:
        return Decimal("0.0000")
    return pct4(Fraction(100) * frac(gross_written_premium_minor)
                / frac(bound_limit_minor))


def rate_change_pct(current_rate, prior_rate):
    if prior_rate is None or dec(prior_rate) == 0:
        return Decimal("0.00")
    return score2((frac(current_rate) / frac(prior_rate) - 1) * 100)


def exposure_change_pct(current_limit, prior_limit):
    if not prior_limit:
        return Decimal("0.00")
    return score2(Fraction(100) * Fraction(current_limit - prior_limit)
                  / Fraction(prior_limit))


def risk_adjusted_rate_change_pct(rate_change, exposure_change):
    return score2(frac(rate_change) - frac(exposure_change) * Fraction(1, 2))


def placement_efficiency_pct(signed_total, written_total):
    if dec(written_total) == 0:
        return Decimal("0.00")
    return score2(Fraction(100) * frac(signed_total) / frac(written_total))


def market_condition_index(risk_adjusted, efficiency):
    return score2(
        frac(Decimal("0.6")) * frac(risk_adjusted)
        + frac(Decimal("0.4")) * (Fraction(100) - frac(efficiency))
    )
