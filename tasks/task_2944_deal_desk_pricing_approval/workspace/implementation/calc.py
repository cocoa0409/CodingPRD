"""Calculations C1-C8 (PRD 3.2, 3.3, 3.4, 3.6, 3.8, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import db

ZERO = Decimal(0)
ONE = Decimal(1)

TERM_MULTIPLIER_UNDER_12 = Decimal("1.10")
TERM_MULTIPLIER_12_TO_23 = Decimal("1.00")
TERM_MULTIPLIER_24_TO_35 = Decimal("0.95")
TERM_MULTIPLIER_36_PLUS = Decimal("0.90")

UPLIFT_BLOCK_DAYS = 30
EXCEPTION_MINIMUM_LEVEL = 3
DOMINANT_MULTIPLIER = Decimal("1.25")
SCORE_CAP = Decimal(100)
MONTHS_PER_YEAR = Decimal(12)

CATEGORY_WEIGHT = {
    "PAYMENT_TERMS": Decimal(20),
    "SLA_COMMITMENT": Decimal(30),
    "INDEMNITY_CAP": Decimal(30),
    "TERMINATION_FOR_CONVENIENCE": Decimal(30),
    "PRICE_HOLD_RENEWAL": Decimal(30),
}


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places (ties away from zero)."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


def term_multiplier(term_months):
    months = int(term_months)
    if months < 12:
        return TERM_MULTIPLIER_UNDER_12
    if months < 24:
        return TERM_MULTIPLIER_12_TO_23
    if months < 36:
        return TERM_MULTIPLIER_24_TO_35
    return TERM_MULTIPLIER_36_PLUS


# ---------------------------------------------------------------- C1 ---------

def _applicable_band(bands, quantity):
    for band in bands:
        max_q = band.get("max_quantity")
        if band["min_quantity"] <= quantity and (max_q is None or quantity <= max_q):
            return band
    return None


def _bundle_discount(line, siblings):
    """First rule (created_at ASC) whose anchor is present on the quote."""
    rules = db.bundle_rules_attached_to(line["product_id"])
    for rule in rules:
        anchor_line = None
        for other in siblings:
            if other["id"] == line["id"]:
                continue
            if other["product_id"] == rule["anchor_product_id"]:
                anchor_line = other
                break
        if anchor_line is None:
            continue
        ratio = dec(line["quantity"]) / dec(anchor_line["quantity"])
        if ratio >= dec(rule["min_attach_quantity_ratio"]):
            return dec(rule["bundle_discount_pct"])
        return ZERO
    return ZERO


def price_line(line, siblings, quote, policy):
    """C1: both band treatments for one line."""
    quantity = int(line["quantity"])
    unit_list = int(line["unit_list_price_cents"])
    unit_cost = int(line["unit_cost_cents"])
    requested = dec(line.get("requested_discount_pct") or 0)
    cap = dec(policy["max_stack_discount_pct"])
    multiplier = term_multiplier(quote["term_months"])

    extended_list = quantity * unit_list
    extended_cost = quantity * unit_cost

    bands = db.bands_of_product(line["product_id"])
    band = _applicable_band(bands, quantity)
    tier_level_applied = band["tier_level"] if band else 0
    band_average = dec(band["tier_discount_pct"]) if band else ZERO

    bundle_pct = _bundle_discount(line, siblings)

    effective_stack = min(band_average + bundle_pct + requested, cap)
    effective_stack = rhu(effective_stack, 6)
    provisional_net = rhu_cents(
        dec(extended_list) * (ONE - effective_stack) * multiplier
    )

    if bands:
        total = ZERO
        for row in bands:
            max_q = row.get("max_quantity")
            upper = quantity if max_q is None else min(quantity, int(max_q))
            units = upper - int(row["min_quantity"]) + 1
            if units <= 0:
                continue
            band_stack = min(dec(row["tier_discount_pct"]) + bundle_pct + requested, cap)
            band_stack = rhu(band_stack, 6)
            total += dec(units) * dec(unit_list) * (ONE - band_stack)
        final_net = rhu_cents(total * multiplier)
    else:
        band_stack = rhu(min(bundle_pct + requested, cap), 6)
        final_net = rhu_cents(
            dec(quantity) * dec(unit_list) * (ONE - band_stack) * multiplier
        )

    return {
        "id": line["id"],
        "extended_list_cents": extended_list,
        "extended_cost_cents": extended_cost,
        "volume_tier_level_applied": tier_level_applied,
        "bundle_discount_applied_pct": bundle_pct,
        "effective_stack_discount_pct": effective_stack,
        "provisional_net_cents": provisional_net,
        "final_net_cents": final_net,
    }


# ---------------------------------------------------------------- C2 ---------

def order_totals(policy, quote, net_subtotal):
    """C2: volume rebate then financing uplift, each rounded separately."""
    subtotal = int(net_subtotal)
    if subtotal >= int(policy["volume_rebate_tier2_min_cents"]):
        rate = dec(policy["volume_rebate_tier2_pct"])
    elif subtotal >= int(policy["volume_rebate_tier1_min_cents"]):
        rate = dec(policy["volume_rebate_tier1_pct"])
    else:
        rate = ZERO
    rebate = rhu_cents(dec(subtotal) * rate)

    extra_days = int(quote["payment_terms_days"]) - int(policy["standard_payment_terms_days"])
    if extra_days < 0:
        extra_days = 0
    periods = ceil_div(extra_days, UPLIFT_BLOCK_DAYS) if extra_days else 0
    uplift = rhu_cents(
        dec(subtotal - rebate) * dec(policy["uplift_rate_per_30_days"]) * dec(periods)
    )
    return {
        "net_subtotal_cents": subtotal,
        "rebate_rate": rate,
        "volume_rebate_cents": rebate,
        "payment_terms_uplift_cents": uplift,
        "net_total_cents": subtotal - rebate + uplift,
    }


# ---------------------------------------------------------------- C3/C4 ------

def blended_discount(list_total, net_subtotal, rebate):
    if int(list_total) == 0:
        return rhu(ZERO, 6)
    base = dec(net_subtotal - rebate) / dec(list_total)
    return rhu(ONE - base, 6)


def margin_pct(net_total, cost_total):
    if int(net_total) == 0:
        return rhu(ZERO, 6)
    return rhu(dec(net_total - cost_total) / dec(net_total), 6)


def matrix_level(policy_id, blended):
    tiers = db.tiers_of_policy(policy_id)
    for tier in tiers:
        if dec(tier["min_discount_pct"]) <= blended < dec(tier["max_discount_pct"]):
            return tier["tier_level"]
    if tiers:
        top = max(tiers, key=lambda t: (dec(t["max_discount_pct"]), t["tier_level"]))
        if blended >= dec(top["max_discount_pct"]):
            return top["tier_level"]
    return 0


def required_level(policy_id, final_blended, has_accepted_exception):
    level = matrix_level(policy_id, final_blended)
    if has_accepted_exception:
        return max(level, EXCEPTION_MINIMUM_LEVEL)
    if final_blended == rhu(ZERO, 6):
        return 0
    return level


def margin_give_up_cents(policy, final_margin, final_net_total):
    """The price of an exception; only charged strictly below the soft floor."""
    floor = dec(policy["margin_floor_pct"])
    if not dec(final_margin) < floor:
        return 0
    return rhu_cents((floor - dec(final_margin)) * dec(final_net_total))


# ---------------------------------------------------------------- C5 ---------

def step_sla(policy, level, created_at):
    """C5: surge flag, effective SLA hours (2dp) and due instant for a step."""
    import clock
    band = db.tier_at_level(policy["id"], level)
    base_hours = dec(band["sla_hours"]) if band else ZERO
    surge = clock.in_surge_window(created_at, policy["surge_window_days"])
    multiplier = dec(policy["surge_sla_multiplier"]) if surge else ONE
    effective = rhu(base_hours * multiplier, 2)
    return {
        "in_surge_window": surge,
        "sla_hours_effective": effective,
        "sla_due_at": clock.add_hours(created_at, effective),
    }


def turnaround_hours(start, end):
    import clock
    return rhu(clock.hours_between(start, end), 2)


def creation_expiry(policy, created_at):
    import clock
    return clock.add_days(created_at, int(policy["quote_validity_days"]))


def approval_expiry(policy, approved_at):
    """C5: re-based validity, truncated to quarter end inside the surge window."""
    import clock
    candidate = clock.add_days(approved_at, int(policy["quote_validity_days"]))
    if clock.in_surge_window(approved_at, policy["surge_window_days"]):
        quarter_end = clock.quarter_end_instant(approved_at)
        if candidate > quarter_end:
            return quarter_end
    return candidate


# ---------------------------------------------------------------- C6 ---------

def severity_factor(term_category, requested_numeric_value):
    value = dec(requested_numeric_value)
    if term_category == "PAYMENT_TERMS":
        ratio = (value - Decimal(30)) / Decimal(120)
    elif term_category == "SLA_COMMITMENT":
        ratio = (value - Decimal("99.9")) / Decimal("0.1")
    elif term_category == "INDEMNITY_CAP":
        ratio = value / Decimal(6)
    elif term_category == "TERMINATION_FOR_CONVENIENCE":
        ratio = (Decimal(12) - value) / Decimal(12)
    elif term_category == "PRICE_HOLD_RENEWAL":
        ratio = value / Decimal(36)
    else:
        ratio = ZERO
    if ratio < ZERO:
        ratio = ZERO
    if ratio > ONE:
        ratio = ONE
    return rhu(ratio, 6)


def risk_contribution(term_category, severity):
    weight = CATEGORY_WEIGHT.get(term_category, ZERO)
    return rhu(weight * dec(severity), 2)


RISK_INPUT_STATES = ("PENDING", "APPROVED", "REJECTED")


def score_terms(quote_id):
    """C6: both quote-level scores plus the dominant term (ties by created_at)."""
    terms = [
        t for t in db.terms_of_quote(quote_id)
        if t["review_state"] in RISK_INPUT_STATES
    ]
    if not terms:
        return {
            "aggregate": rhu(ZERO, 2),
            "dominant": rhu(ZERO, 2),
            "dominant_term": None,
            "terms": terms,
        }
    total = sum((dec(t["risk_contribution"]) for t in terms), ZERO)
    aggregate = min(rhu(total, 2), SCORE_CAP)

    dominant_term = terms[0]
    for term in terms[1:]:
        if dec(term["risk_contribution"]) > dec(dominant_term["risk_contribution"]):
            dominant_term = term
    dominant = min(
        rhu(dec(dominant_term["risk_contribution"]) * DOMINANT_MULTIPLIER, 2),
        SCORE_CAP,
    )
    return {
        "aggregate": aggregate,
        "dominant": dominant,
        "dominant_term": dominant_term,
        "terms": terms,
    }


# ---------------------------------------------------------------- C7 ---------

USAGE_CATEGORY = "USAGE_AS_INCURRED"


def classify_arrangement(lines):
    categories = set()
    for line in lines:
        categories.add(line["rev_rec_category"])
    if len(categories) <= 1:
        return "SINGLE_ELEMENT"
    if USAGE_CATEGORY in categories:
        return "USAGE_BASED_HYBRID"
    return "MULTI_ELEMENT"


def allocate(quote, lines):
    """C7: usage carve-out then a floored proportional waterfall over SSPs."""
    usage_excluded = sum(
        int(l["final_net_cents"]) for l in lines
        if l["rev_rec_category"] == USAGE_CATEGORY
    )
    allocable_amount = int(quote["final_net_total_cents"]) - usage_excluded
    allocable = [l for l in lines if l["rev_rec_category"] != USAGE_CATEGORY]
    ssp_total = sum(int(l["extended_list_cents"]) for l in allocable)

    allocated = {}
    residual = 0
    if allocable:
        running = 0
        for line in allocable[:-1]:
            if ssp_total == 0:
                share = 0
            else:
                share = floor_cents(
                    dec(allocable_amount) * dec(line["extended_list_cents"]) / dec(ssp_total)
                )
            allocated[line["id"]] = share
            running += share
        last = allocable[-1]
        if ssp_total == 0:
            proportional_last = 0
        else:
            proportional_last = floor_cents(
                dec(allocable_amount) * dec(last["extended_list_cents"]) / dec(ssp_total)
            )
        final_last = allocable_amount - running
        allocated[last["id"]] = final_last
        residual = final_last - proportional_last

    allocation_lines = []
    for line in lines:
        if line["rev_rec_category"] == USAGE_CATEGORY:
            allocation_lines.append({
                "quote_line_id": line["id"],
                "ssp_cents": int(line["extended_list_cents"]),
                "allocated_cents": 0,
            })
        else:
            allocation_lines.append({
                "quote_line_id": line["id"],
                "ssp_cents": int(line["extended_list_cents"]),
                "allocated_cents": int(allocated.get(line["id"], 0)),
            })
    return {
        "arrangement_type": classify_arrangement(lines),
        "usage_excluded_cents": usage_excluded,
        "allocable_amount_cents": allocable_amount,
        "allocation_lines": allocation_lines,
        "allocation_residual_cents": residual,
    }


# ---------------------------------------------------------------- C8 ---------

RATABLE_CATEGORY = "RATABLE"


def booking_figures(quote, lines):
    """C8: annualised recurring revenue and total contract value."""
    ratable = sum(
        int(l["final_net_cents"]) for l in lines
        if l["rev_rec_category"] == RATABLE_CATEGORY
    )
    years = dec(quote["term_months"]) / MONTHS_PER_YEAR
    if years == ZERO:
        arr = 0
    else:
        arr = rhu_cents(dec(ratable) / years)
    return {
        "booked_arr_cents": arr,
        "booked_tcv_cents": int(quote["final_net_total_cents"]),
    }
