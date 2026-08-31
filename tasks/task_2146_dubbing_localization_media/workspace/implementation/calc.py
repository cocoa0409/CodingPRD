"""Calculation rules (PRD sections 2.9, 3.4, 3.7, 3.8, 3.9, 3.10, 3.11)."""
from decimal import Decimal, ROUND_HALF_UP

BLOCK_MINUTES = 30
UNION_UPLIFT_PCT = Decimal("0.125")
RETAKE_CREDIT_PCT = Decimal("0.40")

TIER_WEIGHT = {"STANDARD": Decimal("1.00"), "EXPEDITED": Decimal("0.97"), "RUSH": Decimal("0.94")}
RUSH_PCT = {"STANDARD": Decimal("0.00"), "EXPEDITED": Decimal("0.10"), "RUSH": Decimal("0.22")}
DISCOUNT_TIER_1_CENTS = 200000
DISCOUNT_TIER_2_CENTS = 500000

BUYOUT_MULTIPLIER = Decimal("1.75")
RESIDUAL_BANDS = [Decimal("0.45"), Decimal("0.30"), Decimal("0.18")]
RESIDUAL_TAIL_PCT = Decimal("0.07")
RESIDUAL_CAP_PCT = Decimal("1.20")
TERRITORY_ORDER = ["US", "CA", "UK", "DE", "FR", "JP", "BR", "AU", "ROW"]

LOUDNESS_TOLERANCE_LU = Decimal("2.0")
MIN_CONFORMANCE_INDEX = Decimal("0.80")
MAX_RETAKE_CYCLES = 2
MAX_LINEAGE_DEPTH = 3
PRIORITY_RANK = {"RUSH": 0, "EXPEDITED": 1, "STANDARD": 2}

_ONE = Decimal(1)
_FOUR_DP = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_cents(value):
    """Round half up to a whole cent."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """Round half up to four decimal places; returned as a float for JSON."""
    return float(dec(value).quantize(_FOUR_DP, rounding=ROUND_HALF_UP))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------
# session_cost_cents
# --------------------------------------------------------------------------
def session_cost_cents(duration_minutes, hourly_rate_cents, agreed_rate_cents_per_hour,
                       union_status, is_retake):
    duration = dec(duration_minutes)
    blocks = ceil_div(int(duration_minutes), BLOCK_MINUTES) if duration_minutes > 0 else 0
    billable_minutes = dec(blocks * BLOCK_MINUTES)
    sixty = dec(60)

    studio_line = round_cents(dec(hourly_rate_cents) * billable_minutes / sixty)
    talent_line = round_cents(dec(agreed_rate_cents_per_hour) * duration / sixty)
    if union_status == "UNION":
        union_uplift = round_cents(UNION_UPLIFT_PCT * dec(agreed_rate_cents_per_hour) * duration / sixty)
    else:
        union_uplift = 0
    if is_retake:
        retake_credit = round_cents(RETAKE_CREDIT_PCT * dec(agreed_rate_cents_per_hour) * duration / sixty)
    else:
        retake_credit = 0
    return studio_line + talent_line + union_uplift - retake_credit


# --------------------------------------------------------------------------
# adaptation_fidelity_score
# --------------------------------------------------------------------------
def provisional_fidelity_score(declared_loop_count, cut_loop_count, priority_tier):
    weight = TIER_WEIGHT[priority_tier]
    declared = dec(declared_loop_count)
    loops = dec(cut_loop_count)
    coverage = declared / loops
    if coverage > _ONE:
        coverage = _ONE
    density = (declared - loops) / loops
    if density < 0:
        density = Decimal(0)
    capped_density = density if density < _ONE else _ONE
    weighted = Decimal("0.60") * coverage + Decimal("0.40") * (_ONE - capped_density)
    return round4(weighted * weight)


def final_fidelity_score(measured_total_ms, lines_over_deviation, declared_loop_count,
                         max_lipsync_deviation_ms, priority_tier):
    weight = TIER_WEIGHT[priority_tier]
    denom = dec(max(1, declared_loop_count))
    avg_dev = dec(measured_total_ms) / denom
    dev_ratio = avg_dev / dec(max_lipsync_deviation_ms)
    if dev_ratio > _ONE:
        dev_ratio = _ONE
    over_ratio = dec(lines_over_deviation) / denom
    if over_ratio > _ONE:
        over_ratio = _ONE
    weighted = Decimal("0.55") * (_ONE - dev_ratio) + Decimal("0.45") * (_ONE - over_ratio)
    return round4(weighted * weight)


# --------------------------------------------------------------------------
# mix_conformance_index
# --------------------------------------------------------------------------
def conformance_index(loudness_lufs, loudness_target_lufs, me_stem_present,
                      job_stem_layout, spec_stem_layout, character_count, recorded_count):
    delta = abs(dec(loudness_lufs) - dec(loudness_target_lufs))
    loudness_score = _ONE - delta / LOUDNESS_TOLERANCE_LU
    if loudness_score < 0:
        loudness_score = Decimal(0)
    stem_score = _ONE if (me_stem_present and job_stem_layout == spec_stem_layout) else Decimal(0)
    if character_count == 0:
        cast_coverage = Decimal(0)
    else:
        cast_coverage = dec(recorded_count) / dec(character_count)
        if cast_coverage > _ONE:
            cast_coverage = _ONE
    index = (Decimal("0.40") * loudness_score + Decimal("0.35") * stem_score
             + Decimal("0.25") * cast_coverage)
    return round4(index)


# --------------------------------------------------------------------------
# qc_pass_rate
# --------------------------------------------------------------------------
def qc_pass_rate(defect_count, sampled_loop_count):
    return round4(_ONE - dec(defect_count) / dec(sampled_loop_count))


# --------------------------------------------------------------------------
# talent_usage_fee_cents
# --------------------------------------------------------------------------
def base_fee_cents(agreed_rate_cents_per_hour, durations):
    total = 0
    for duration in durations:
        total += round_cents(dec(agreed_rate_cents_per_hour) * dec(duration) / dec(60))
    return total


def usage_fee_cents(base_fee, variant, territory_scope):
    if variant == "BUYOUT":
        return round_cents(dec(base_fee) * BUYOUT_MULTIPLIER)
    ordered = sorted(
        [t for t in territory_scope],
        key=lambda t: TERRITORY_ORDER.index(t) if t in TERRITORY_ORDER else len(TERRITORY_ORDER),
    )
    band_total = Decimal(0)
    for index, _terr in enumerate(ordered):
        band_total += RESIDUAL_BANDS[index] if index < len(RESIDUAL_BANDS) else RESIDUAL_TAIL_PCT
    if band_total > RESIDUAL_CAP_PCT:
        band_total = RESIDUAL_CAP_PCT
    return round_cents(dec(base_fee) * band_total)


# --------------------------------------------------------------------------
# order_invoice_total_cents
# --------------------------------------------------------------------------
def invoice(order_id, completed_session_costs, priority_tier):
    recorded_subtotal = sum(completed_session_costs)
    rush_surcharge = round_cents(dec(recorded_subtotal) * RUSH_PCT[priority_tier])
    pre_discount_total = recorded_subtotal + rush_surcharge
    if pre_discount_total >= DISCOUNT_TIER_2_CENTS:
        pct = Decimal("0.08")
    elif pre_discount_total >= DISCOUNT_TIER_1_CENTS:
        pct = Decimal("0.05")
    else:
        pct = Decimal("0.00")
    discount = round_cents(dec(pre_discount_total) * pct)
    return {
        "order_id": order_id,
        "recorded_subtotal_cents": recorded_subtotal,
        "rush_surcharge_cents": rush_surcharge,
        "pre_discount_total_cents": pre_discount_total,
        "volume_discount_pct": float(pct),
        "volume_discount_cents": discount,
        "invoice_total_cents": pre_discount_total - discount,
    }
