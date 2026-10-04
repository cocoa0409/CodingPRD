"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3.5, §3.6, §3.9).

All money and credit quantities use Decimal; every rounding the system
performs is round-half-up to two decimal places, applied in the pinned order
per rule.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import STORE, get_clock

# --- mitigation_credit_requirement constants -------------------------------
RATIO_BY_TYPE = {
    "EMERGENT_MARSH": Decimal("2.0"),
    "FORESTED_WETLAND": Decimal("3.0"),
    "OPEN_WATER": Decimal("1.5"),
    "STREAM": Decimal("1.0"),
}
LOCATION_MULT_IN_BASIN = Decimal("1.0")
LOCATION_MULT_OUT_OF_BASIN = Decimal("1.25")
LAG_TIER1_MAX_DAYS = 365
LAG_TIER2_MAX_DAYS = 730
LAG_MULT_TIER1 = Decimal("1.0")
LAG_MULT_TIER2 = Decimal("1.10")
LAG_MULT_TIER3 = Decimal("1.20")
ATF_MULTIPLIER = Decimal("1.5")

# --- in_lieu_fee_amount constants ------------------------------------------
ILF_RATE_PER_CREDIT = {
    "EMERGENT_MARSH": Decimal("40000"),
    "FORESTED_WETLAND": Decimal("55000"),
    "OPEN_WATER": Decimal("30000"),
    "STREAM": Decimal("25000"),
}

# --- public_interest_review_score constants --------------------------------
W_ENVIRONMENTAL = Decimal("0.40")
W_ECONOMIC = Decimal("0.35")
W_NAVIGATION = Decimal("0.25")
ECONOMIC_NEUTRAL_DOLLARS = Decimal("250000.0")
ECONOMIC_SCALE_DOLLARS = Decimal("10000.0")

# --- enforcement_penalty_accrual constants ---------------------------------
PENALTY_RATE_PER_ACRE_DAY = Decimal("250.0")
PENALTY_CAP_DOLLARS = Decimal("500000.0")
RESTORATION_GOOD_FAITH_OFFSET = Decimal("0.5")
RESTORATION_DEADLINE_DAYS = 90
EXTENSION_DAYS = 60

# --- bank_credit_pricing constants ------------------------------------------
TIER1_MAX_FRACTION = Decimal("0.5")
TIER2_MAX_FRACTION = Decimal("0.8")
TIER1_MULT = Decimal("1.0")
TIER2_MULT = Decimal("1.15")
TIER3_MULT = Decimal("1.30")

# --- monitoring_schedule_generation constants -------------------------------
MONITORING_REPORT_COUNT = 5
MONITORING_INTERVAL_DAYS = 365
OVERDUE_BREACH_DAYS = 60

JD_VALIDITY_DAYS = 1825
APPEAL_WINDOW_DAYS = 60


def q2(value):
    """Round half-up to two decimal places."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def per_type_acres(application):
    """Aggregate the application's impacts into {resource_type: acres}.

    Lines sharing a resource type have their acreages summed before the
    per-type ratio is applied (the requirement map is keyed by type).
    """
    totals = {}
    for line in application["impacts"]:
        rtype = line["resource_type"]
        acres = line["impact_acres"]
        totals[rtype] = totals.get(rtype, Decimal("0")) + acres
    return totals


def provisional_credits(application):
    """Provisional variant: location and lag multipliers fixed at 1.0.

    Multiplier order pinned: base_ratio, then location, then lag, then ATF.
    """
    atf = ATF_MULTIPLIER if application["is_after_the_fact"] else Decimal("1.0")
    result = {}
    for rtype, acres in per_type_acres(application).items():
        result[rtype] = q2(acres * RATIO_BY_TYPE[rtype]
                           * LOCATION_MULT_IN_BASIN * LAG_MULT_TIER1 * atf)
    return result


def lag_multiplier(submitted_date, clock):
    """Whole days from submitted_date to clock; tiered 1.0 / 1.10 / 1.20."""
    if submitted_date is None:
        return LAG_MULT_TIER1
    lag_days = int((clock - submitted_date).total_seconds() // 86400)
    if lag_days <= LAG_TIER1_MAX_DAYS:
        return LAG_MULT_TIER1
    if lag_days <= LAG_TIER2_MAX_DAYS:
        return LAG_MULT_TIER2
    return LAG_MULT_TIER3


def location_multiplier(application, plan):
    """1.0 iff every PURCHASED transaction of the plan draws on an in-basin
    bank (service_area_watersheds contains the site watershed_code), else
    1.25. PERMITTEE_RESPONSIBLE is always 1.0. With zero PURCHASED
    transactions the universal condition holds vacuously -> 1.0.
    """
    if plan["mechanism"] == "PERMITTEE_RESPONSIBLE":
        return LOCATION_MULT_IN_BASIN
    site = STORE["sites"].get(application["site_id"])
    watershed = site["watershed_code"] if site else None
    for txn in STORE["credit_txns"].values():
        if txn["plan_id"] != plan["id"] or txn["status"] != "PURCHASED":
            continue
        bank = STORE["banks"].get(txn["bank_id"])
        if bank is None or watershed not in bank["service_area_watersheds"]:
            return LOCATION_MULT_OUT_OF_BASIN
    return LOCATION_MULT_IN_BASIN


def final_credits(application, plan):
    """Final variant evaluated at secure-credits / pay-in-lieu-fee."""
    atf = ATF_MULTIPLIER if application["is_after_the_fact"] else Decimal("1.0")
    location = location_multiplier(application, plan)
    lag = lag_multiplier(application["submitted_date"], get_clock())
    result = {}
    for rtype, acres in per_type_acres(application).items():
        result[rtype] = q2(acres * RATIO_BY_TYPE[rtype] * location * lag * atf)
    return result


def ilf_fee(required_credits_by_type):
    """Per-type line rounded to cents FIRST, then the rounded lines summed."""
    total = Decimal("0")
    for rtype, credits in required_credits_by_type.items():
        total += q2(credits * ILF_RATE_PER_CREDIT[rtype])
    return total


def assurance_required(required_credits_by_type):
    """Financial assurance required for PERMITTEE_RESPONSIBLE / COMBINATION.

    INTERPRETATION: neither PRD nor scaffold pins a formula for
    assurance_required_dollars. We derive it from the credit requirement
    using the only per-credit dollar rates the spec declares (the in-lieu
    fee rates), rounded per line then summed — the same pinned rounding
    order as in_lieu_fee_amount. At creation/PATCH it is computed from the
    provisional requirement; at secure-credits it is recomputed from the
    final requirement ("the recomputed assurance_required_dollars").
    """
    return ilf_fee(required_credits_by_type)


def pir_score(application):
    """Public interest review score (PRD §3.5); returns (score, outcome)."""
    total_impact = application["total_impact_acres"]
    is_atf = application["is_after_the_fact"]

    steps = 0
    for aa in STORE["analyses"].values():
        if aa["application_id"] == application["id"] and aa["status"] == "ACCEPTED":
            steps = len(aa["minimization_steps"])
            break

    secured_bonus = Decimal("0.0")
    for plan in STORE["plans"].values():
        if (plan["application_id"] == application["id"]
                and plan["status"] in ("CREDITS_SECURED", "ACTIVE", "COMPLETED")):
            secured_bonus = Decimal("20.0")
            break

    unresolved_advisory = 0
    concurrence_count = 0
    for comment in STORE["comments"].values():
        if comment["application_id"] != application["id"]:
            continue
        if comment["comment_type"] == "ADVISORY" and comment["status"] == "FILED":
            unresolved_advisory += 1
        if comment["comment_type"] == "CONCURRENCE":
            concurrence_count += 1

    if is_atf:
        environmental = (Decimal("-15.0") * total_impact
                         + Decimal("5.0") * steps + secured_bonus
                         - Decimal("15.0") * unresolved_advisory
                         + Decimal("5.0") * concurrence_count
                         - Decimal("10.0"))
    else:
        environmental = (Decimal("-10.0") * total_impact
                         + Decimal("5.0") * steps + secured_bonus
                         - Decimal("15.0") * unresolved_advisory
                         + Decimal("5.0") * concurrence_count)

    economic = (application["estimated_cost_dollars"] - ECONOMIC_NEUTRAL_DOLLARS) \
        / ECONOMIC_SCALE_DOLLARS
    if economic < Decimal("-100.0"):
        economic = Decimal("-100.0")
    elif economic > Decimal("100.0"):
        economic = Decimal("100.0")

    touches_water = any(
        line["resource_type"] in ("OPEN_WATER", "STREAM")
        for line in application["impacts"]
    )
    navigation = Decimal("-10.0") if touches_water else Decimal("15.0")

    score = q2(W_ENVIRONMENTAL * environmental
               + W_ECONOMIC * economic
               + W_NAVIGATION * navigation)
    outcome = "FAVORABLE" if score >= 0 else "UNFAVORABLE"
    return score, outcome


def penalty_accrued(case, clock=None):
    """Daily accrual evaluated against the current logical clock.

    Whole days elapsed from confirmed_date (floor of seconds/86400); 0 while
    unconfirmed; capped at PENALTY_CAP_DOLLARS. Exact (unrounded) accrual.
    """
    if clock is None:
        clock = get_clock()
    if case.get("confirmed_date") is None:
        return Decimal("0")
    days = int((clock - case["confirmed_date"]).total_seconds() // 86400)
    if days < 0:
        days = 0
    raw = case["unauthorized_fill_acres"] * PENALTY_RATE_PER_ACRE_DAY * days
    if raw > PENALTY_CAP_DOLLARS:
        raw = PENALTY_CAP_DOLLARS
    return raw


def bank_inventory(bank):
    """Aggregate RESERVED/PURCHASED/available per type plus revenue.

    Maps cover all four resource types (types missing from credit_capacity
    have capacity 0). Capacity == available + reserved + purchased holds at
    all times.
    """
    from helpers import RESOURCE_TYPES
    capacity = {}
    for rtype in RESOURCE_TYPES:
        capacity[rtype] = bank["credit_capacity"].get(rtype, Decimal("0"))
    reserved = {rtype: Decimal("0") for rtype in RESOURCE_TYPES}
    purchased = {rtype: Decimal("0") for rtype in RESOURCE_TYPES}
    revenue = Decimal("0")
    for txn in STORE["credit_txns"].values():
        if txn["bank_id"] != bank["id"]:
            continue
        rtype = txn["resource_type"]
        if txn["status"] == "RESERVED":
            reserved[rtype] = reserved.get(rtype, Decimal("0")) + txn["credits"]
        elif txn["status"] == "PURCHASED":
            purchased[rtype] = purchased.get(rtype, Decimal("0")) + txn["credits"]
            revenue += txn["total_price_dollars"]
        elif txn["status"] == "REFUNDED":
            # PRD §3.6: refunding moves PURCHASED -> REFUNDED "restoring
            # both inventory and revenue". A refunded transaction was itself
            # purchased, so its price enters both sums of the revenue
            # invariant (sum over PURCHASED minus sum over REFUNDED) and
            # cancels: a purchase-then-refund pair leaves revenue unchanged.
            pass
    available = {rtype: capacity[rtype] - reserved.get(rtype, Decimal("0"))
                 - purchased.get(rtype, Decimal("0")) for rtype in RESOURCE_TYPES}
    return reserved, purchased, available, revenue


def purchase_pricing(bank, resource_type, credits):
    """Tier-adjusted price from the PRE-transaction purchased fraction.

    Only PURCHASED transactions move the tier; this purchase never moves its
    own tier. Unit price rounded half-up to cents first, then multiplied by
    credits and rounded half-up again.
    """
    from helpers import RESOURCE_TYPES  # noqa: F401  (kept for symmetry)
    _, purchased, _, _ = bank_inventory(bank)
    capacity = bank["credit_capacity"].get(resource_type, Decimal("0"))
    pre_purchased = purchased.get(resource_type, Decimal("0"))
    sold_fraction = (pre_purchased / capacity) if capacity > 0 else Decimal("0")
    if sold_fraction < TIER1_MAX_FRACTION:
        mult = TIER1_MULT
    elif sold_fraction < TIER2_MAX_FRACTION:
        mult = TIER2_MULT
    else:
        mult = TIER3_MULT
    unit = q2(bank["base_price_per_credit"][resource_type] * mult)
    total = q2(credits * unit)
    return unit, total
