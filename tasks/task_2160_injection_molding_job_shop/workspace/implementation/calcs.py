"""Integer arithmetic: every quantity is a whole number — cents, grams,
minutes, seconds and basis points. No floating point anywhere."""

# ---- constants -------------------------------------------------------------
LOT_PARTS = 1000
PACKAGING_CENTS_PER_LOT = 1800
TOOLING_AMORT_LOTS = 50
STANDARD_YIELD_BP = 9700
MIN_PIECE_PRICE_CENTS = 12
VOLUME_BREAK_MID = 50000
VOLUME_BREAK_HIGH = 250000
MARGIN_BP_TIER_LOW = 2800
MARGIN_BP_TIER_MID = 2200
MARGIN_BP_TIER_HIGH = 1600

OVERHEAD_BREAK_MID = 500000
OVERHEAD_BREAK_HIGH = 2000000
OVERHEAD_BP_TIER_LOW = 3500
OVERHEAD_BP_TIER_MID = 2800
OVERHEAD_BP_TIER_HIGH = 2200

DEFAULT_MAX_REGRIND_BP = 1500
MIN_FAI_SAMPLE_SHOTS = 30
MAX_MOISTURE_BP = 200
RUN_AT_RATE_MIN_BP = 9000

CHANGEOVER_BUFFER_MINUTES = 45
PRESS_DAILY_CAPACITY_MINUTES = 1224

GOODWILL_WAIVER_BP = 1000
GOODWILL_RATE_BP = 5000
PRESS_AVAILABILITY_BP = 8500


# ---- rounding --------------------------------------------------------------
def round_half_up(numerator, denominator):
    """Exact quotient rounded to the nearest whole number; an exact half rounds
    upward. Defined for non-negative integers."""
    if denominator == 0:
        return 0
    return (2 * numerator + denominator) // (2 * denominator)


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


# ---- quote_piece_price -----------------------------------------------------
def margin_tier(annual_volume):
    if annual_volume < VOLUME_BREAK_MID:
        return MARGIN_BP_TIER_LOW
    if annual_volume < VOLUME_BREAK_HIGH:
        return MARGIN_BP_TIER_MID
    return MARGIN_BP_TIER_HIGH


def piece_price(cavitation, cycle_time_sec, hourly_rate_cents, part_weight_grams,
                resin_price_cents_per_kg, ownership, tooling_cost_cents,
                annual_volume, yield_bp):
    """The eleven pricing steps of §3.3. Returns
    (margin_bp, lot_price_cents, piece_price_cents)."""
    shots_per_lot = ceil_div(LOT_PARTS, cavitation)
    machine_seconds = shots_per_lot * cycle_time_sec
    machine_cost_cents = round_half_up(machine_seconds * hourly_rate_cents, 3600)
    divisor = yield_bp if yield_bp and yield_bp > 0 else 1
    gross_resin_grams = ceil_div(LOT_PARTS * part_weight_grams * 10000, divisor)
    resin_cost_cents = round_half_up(gross_resin_grams * resin_price_cents_per_kg, 1000)
    if ownership == "SHOP_OWNED":
        tooling_cents = ceil_div(tooling_cost_cents, TOOLING_AMORT_LOTS)
    else:
        tooling_cents = 0
    direct_lot_cents = (machine_cost_cents + resin_cost_cents + tooling_cents
                        + PACKAGING_CENTS_PER_LOT)
    margin_bp = margin_tier(annual_volume)
    lot_price_cents = round_half_up(direct_lot_cents * (10000 + margin_bp), 10000)
    piece_cents = max(MIN_PIECE_PRICE_CENTS, ceil_div(lot_price_cents, LOT_PARTS))
    return margin_bp, lot_price_cents, piece_cents


# ---- job cost roll ---------------------------------------------------------
def report_line_cost(run_minutes, hourly_rate_cents, virgin_grams, regrind_grams,
                     resin_price_cents_per_kg):
    machine = round_half_up(run_minutes * hourly_rate_cents, 60)
    material = round_half_up((virgin_grams + regrind_grams) * resin_price_cents_per_kg, 1000)
    return machine + material


def overhead_tier(direct_cost_cents):
    if direct_cost_cents < OVERHEAD_BREAK_MID:
        return OVERHEAD_BP_TIER_LOW
    if direct_cost_cents < OVERHEAD_BREAK_HIGH:
        return OVERHEAD_BP_TIER_MID
    return OVERHEAD_BP_TIER_HIGH


# ---- run at rate -----------------------------------------------------------
def achievement_bp(actual_parts_per_hour, target_parts_per_hour):
    return floor_div(actual_parts_per_hour * 10000, target_parts_per_hour)


# ---- capacity settlement ---------------------------------------------------
def strict_shortfall_fee(shortfall_minutes, hourly_rate_cents):
    return round_half_up(shortfall_minutes * hourly_rate_cents, 60)


def goodwill_shortfall_fee(shortfall_minutes, committed_minutes, hourly_rate_cents):
    waived = floor_div(committed_minutes * GOODWILL_WAIVER_BP, 10000)
    billable = max(0, shortfall_minutes - waived)
    return round_half_up(billable * hourly_rate_cents * GOODWILL_RATE_BP, 60 * 10000)


# ---- intervals -------------------------------------------------------------
def minutes_between(start, end):
    return int((end - start).total_seconds()) // 60


def press_collides(cand_start, cand_end, exist_start, exist_end):
    """Half-open press windows separated by a mandatory 45-minute changeover
    applied to the gap between them."""
    buffer_delta = CHANGEOVER_BUFFER_MINUTES * 60
    gap_after = (cand_start - exist_end).total_seconds() >= buffer_delta
    gap_before = (exist_start - cand_end).total_seconds() >= buffer_delta
    return not (gap_after or gap_before)


def mold_collides(cand_start, cand_end, exist_start, exist_end):
    """Closed mold windows with zero buffer: occupancies that merely touch at an
    endpoint do collide."""
    return cand_start <= exist_end and exist_start <= cand_end
