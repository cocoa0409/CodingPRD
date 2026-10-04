"""Calculation rules (SCAFFOLD §1.3 / PRD §3). Money is integer cents; every
pinned rounding step uses Decimal ROUND_HALF_UP at exactly the step the spec
pins. Never round a total first and derive a unit from it."""

from decimal import Decimal, ROUND_HALF_UP

import constants
from store import STORE
from validation import windows_overlap

TIER_DISCOUNTS = {
    "CONVERTER_AUTHORIZED": Decimal(str(constants.TIER_DISCOUNT_CONVERTER_AUTHORIZED)),
    "DISTRIBUTOR_PREFERRED": Decimal(str(constants.TIER_DISCOUNT_DISTRIBUTOR_PREFERRED)),
    "STANDARD": Decimal(str(constants.TIER_DISCOUNT_STANDARD)),
}

DISCLOSURE_RANK = {"EXEMPT": 0, "DECLARATION": 1, "FULL_DISCLOSURE": 2}

ADHESION_NOMINALS = {
    "METAL": Decimal(str(constants.ADHESION_THRESHOLD_METAL)),
    "POLYMER": Decimal(str(constants.ADHESION_THRESHOLD_POLYMER)),
    "GLASS": Decimal(str(constants.ADHESION_THRESHOLD_GLASS)),
    "COMPOSITE": Decimal(str(constants.ADHESION_THRESHOLD_COMPOSITE)),
}

_CENT = Decimal("1")
_TWO_DP = Decimal("0.01")


def _dec(value):
    """Decimal from a JSON number without binary-float artifacts."""
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# required_disclosure_level — max ppm over REPORTABLE/RESTRICTED components vs
# jurisdiction thresholds; both boundaries inclusive at the lower edge.
# ---------------------------------------------------------------------------

def required_disclosure_level(formulation_id, jurisdiction):
    relevant_ppm = []
    for comp in STORE["components"].values():
        if comp["formulation_id"] != formulation_id:
            continue
        substance = STORE["substances"].get(comp["substance_id"])
        if substance is None:
            continue
        if substance["restriction_class"] in ("REPORTABLE", "RESTRICTED"):
            relevant_ppm.append(comp["concentration_ppm"])
    if not relevant_ppm:
        return "EXEMPT"
    max_ppm = max(relevant_ppm)
    if max_ppm < jurisdiction["declaration_threshold_ppm"]:
        return "EXEMPT"
    if max_ppm < jurisdiction["full_disclosure_threshold_ppm"]:
        return "DECLARATION"
    return "FULL_DISCLOSURE"


def formulation_has_prohibited_component(formulation_id):
    """True when any component references a PROHIBITED substance at > 0 ppm."""
    for comp in STORE["components"].values():
        if comp["formulation_id"] != formulation_id:
            continue
        substance = STORE["substances"].get(comp["substance_id"])
        if (substance is not None
                and substance["restriction_class"] == "PROHIBITED"
                and comp["concentration_ppm"] > 0):
            return True
    return False


# ---------------------------------------------------------------------------
# order_unit_price — tier discount + single best applicable breakpoint over the
# WHOLE quantity (average-rate, not marginal); round once at the unit price,
# then multiply.
# ---------------------------------------------------------------------------

def order_unit_price(agreement, quantity):
    tier_discount = TIER_DISCOUNTS[agreement["tier"]]
    eligible = [bp for bp in agreement["volume_breakpoints"]
                if bp["min_qty"] <= quantity]
    extra = max((_dec(bp["extra_discount_pct"]) for bp in eligible),
                default=Decimal("0"))
    effective_discount = tier_discount + extra
    unit = int((Decimal(agreement["base_price_cents"]) * (1 - effective_discount))
               .quantize(_CENT, rounding=ROUND_HALF_UP))
    return unit, unit * quantity


# ---------------------------------------------------------------------------
# rebate_accrual_amount — marginal per-tier brackets over orders processed in
# chronological order (shipped_at ASC, tie-break created_at ASC); each order's
# per-tier portion rounded to cents FIRST, then summed.
# ---------------------------------------------------------------------------

def _partner_orders_in_period(program):
    rows = []
    for order in STORE["orders"].values():
        if order["formulation_id"] != program["formulation_id"]:
            continue
        if program["converter_id"] is not None:
            if order["converter_id"] != program["converter_id"]:
                continue
        elif program["distributor_id"] is not None:
            if order["distributor_id"] != program["distributor_id"]:
                continue
        if order["fulfillment_status"] != "SHIPPED" or order["shipped_at"] is None:
            continue
        if not (program["period_start"] <= order["shipped_at"] < program["period_end"]):
            continue
        rows.append(order)
    return rows


def rebate_accrual_amount(program, final):
    """Returns (amount_cents, excluded_order_count). The provisional variant
    includes FLAGGED shipped orders; the final variant excludes them and
    re-baselines the cumulative quantity over the reduced set."""
    orders = _partner_orders_in_period(program)
    excluded = sum(1 for o in orders if o["compliance_status"] == "FLAGGED")
    if final:
        orders = [o for o in orders if o["compliance_status"] == "CLEAR"]
    orders.sort(key=lambda o: (o["shipped_at"], o["created_at"], o["_seq"]))
    tiers = sorted(program["rebate_tiers"], key=lambda t: t["threshold_qty"])
    total = 0
    cumulative = 0
    for order in orders:
        qty = order["quantity"]
        unit = Decimal(order["unit_price_cents"])
        order_accrual = 0
        span_lo, span_hi = cumulative, cumulative + qty
        for i, tier in enumerate(tiers):
            tier_lo = tier["threshold_qty"]
            tier_hi = tiers[i + 1]["threshold_qty"] if i + 1 < len(tiers) else None
            upper = span_hi if tier_hi is None else min(span_hi, tier_hi)
            portion = max(0, upper - max(span_lo, tier_lo))
            if portion > 0:
                cents = (Decimal(portion) * unit * _dec(tier["rate_pct"])) \
                    .quantize(_CENT, rounding=ROUND_HALF_UP)
                order_accrual += int(cents)
        total += order_accrual
        cumulative += qty
    return total, excluded


# ---------------------------------------------------------------------------
# adhesion_pass_evaluation — nominal per substrate; APPLICATION_DERATED scales
# +3% per full 10C deviation from 23C, rounded half-up to 2dp; pass is
# inclusive (peel >= threshold).
# ---------------------------------------------------------------------------

def adhesion_threshold(substrate_class, test_standard, test_temp_c):
    nominal = ADHESION_NOMINALS[substrate_class]
    if test_standard == "NOMINAL":
        return nominal
    steps = abs(test_temp_c - constants.NOMINAL_TEMP_C) // 10
    factor = 1 + Decimal(str(constants.DERATE_PCT_PER_10C)) * steps
    return (nominal * factor).quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def adhesion_pass(substrate_class, test_standard, test_temp_c, peel):
    threshold = adhesion_threshold(substrate_class, test_standard, test_temp_c)
    return _dec(peel) >= threshold, threshold


# ---------------------------------------------------------------------------
# channel_price_floor — distributor agreements only. Reference set: converter
# agreements on the same (formulation, jurisdiction) with overlapping windows.
# floor = min(ref unit at qty 1) * 1.08; reject when this agreement's
# worst-case unit price is below the floor.
# ---------------------------------------------------------------------------

def channel_floor_violation(formulation_id, jurisdiction_id, tier,
                            base_price_cents, volume_breakpoints,
                            effective_from, effective_to):
    references = []
    for other in STORE["agreements"].values():
        if other["converter_id"] is None:
            continue
        if other["formulation_id"] != formulation_id:
            continue
        if other["jurisdiction_id"] != jurisdiction_id:
            continue
        if windows_overlap(other["effective_from"], other["effective_to"],
                           effective_from, effective_to):
            references.append(other)
    if not references:
        return False
    ref_units = [
        int((Decimal(ref["base_price_cents"]) * (1 - TIER_DISCOUNTS[ref["tier"]]))
            .quantize(_CENT, rounding=ROUND_HALF_UP))
        for ref in references
    ]
    floor = int((Decimal(min(ref_units))
                 * (1 + Decimal(str(constants.CHANNEL_MARGIN_MIN_PCT))))
                .quantize(_CENT, rounding=ROUND_HALF_UP))
    max_extra = max((_dec(bp["extra_discount_pct"]) for bp in volume_breakpoints),
                    default=Decimal("0"))
    distributor_min = int(
        (Decimal(base_price_cents) * (1 - TIER_DISCOUNTS[tier] - max_extra))
        .quantize(_CENT, rounding=ROUND_HALF_UP))
    return distributor_min < floor


# ---------------------------------------------------------------------------
# bench_daily_capacity — sum of bench_hours over LAB_BOOKED cases on the same
# (bench_id, bench day) must stay <= 8.0; boundary inclusive.
# ---------------------------------------------------------------------------

def bench_occupied_hours(bench_id, bench_dt):
    day = bench_dt.date()
    total = Decimal("0")
    for case in STORE["cases"].values():
        if case["status"] != "LAB_BOOKED":
            continue
        if case["bench_id"] != bench_id or case["bench_date"] is None:
            continue
        if case["bench_date"].date() != day:
            continue
        total += _dec(case["bench_hours"])
    return total


def bench_admission_ok(bench_id, bench_dt, hours):
    occupied = bench_occupied_hours(bench_id, bench_dt)
    return occupied + _dec(hours) <= Decimal(str(constants.LAB_BENCH_DAILY_HOURS))


# ---------------------------------------------------------------------------
# Phase-out helpers — an affected formulation contains the program's substance
# at >= trigger concentration (integer ppm, >= inclusive).
# ---------------------------------------------------------------------------

def formulation_is_affected(formulation_id, program):
    for comp in STORE["components"].values():
        if comp["formulation_id"] != formulation_id:
            continue
        if (comp["substance_id"] == program["substance_id"]
                and comp["concentration_ppm"] >= program["trigger_concentration_ppm"]):
            return True
    return False
