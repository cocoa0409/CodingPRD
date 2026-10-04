"""Every calculation rule from §1.3, implemented exactly as declared.

Money is integer cents and rates are integer basis points (10000 = whole).
All rate arithmetic goes through Decimal with ROUND_HALF_UP; floating point is
never used for money (PRD §2.7).
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- engineer_commission_cents ---
COMMISSION_POOL_BPS = 800

# --- package_bundle_price_cents ---
SYSTEM_LINE_DISCOUNT_BPS = 6667
TIER_HIGH_CENTS = 500000
TIER_HIGH_BPS = 1000
TIER_MID_CENTS = 200000
TIER_MID_BPS = 500

# --- warranty_service_fee_cents ---
BASE_ROUND_FEE_CENTS = 2500
TERM_MONTHS_BASELINE = 24

# --- instrument_inspection_verdict ---
ACTION_MIN_MM = 0.50
ACTION_MAX_MM = 2.00
RELIEF_MIN_MM = 0.05
INTONATION_TOLERANCE_CENTS = 5

# --- gear_exchange_restocking_fee ---
REASON_BPS = {
    "TONE_MISMATCH": 1500,
    "DEFECT_DOA": 0,
    "WRONG_MODEL": 800,
    "CHANGED_MIND": 2500,
}
TIER_ADJUST_BPS = {"STANDARD": 0, "PREMIUM": -500, "STUDIO": -1000}
NEAR_EXPIRY_DAYS = 3
NEAR_EXPIRY_BPS = 500

# --- customer_tech_support_entitlement ---
MIN_PURCHASES_FOR_BASIC = 1

# --- engineer_seniority_tier ---
TIER_2_MIN = 2
TIER_3_MIN = 4
TIER_CAPS = {"TIER_1": 5000, "TIER_2": 6500, "TIER_3": 7500}

# --- temporal constants (PRD §2.6) ---
BACKORDER_WINDOW_DAYS = 30
TRIAL_WINDOW_DAYS = 14
CERT_VALIDITY_MONTHS = 12

MAX_REPAIR_ROUNDS = 3

PRODUCT_FAMILIES = ("GUITAR", "AMPLIFIER", "INTERFACE", "MICROPHONE",
                    "EFFECT_PEDAL", "ACCESSORY")


def money(value):
    """Round a cent value half-up to its whole-cent representation.

    PRD §2.7 states the rounding as "2 decimal places, round half up" and notes
    that the result is mathematically a whole number of cents once rounded --
    the unit *is* the cent.  Rounding is therefore half-up to the nearest cent
    (never banker's rounding, never truncation), so an intermediate of 3999.5
    cents resolves to 4000 rather than being cut down.
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def half_up(value, places):
    """Round a Decimal/str/number half-up at `places` and return a float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return float(value.quantize(quantum, rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, bps):
    """amount * bps / 10000, rounded once half-up to 2 decimals."""
    return money(Decimal(amount_cents) * Decimal(bps) / Decimal(10000))


# ---------------------------------------------------------------------------
# engineer_commission_cents (dual_variant)
# ---------------------------------------------------------------------------

def commission_pool_cents(quote_gross_subtotal_cents):
    return apply_bps(quote_gross_subtotal_cents, COMMISSION_POOL_BPS)


def engineer_commission_cents(quote, gross_subtotal_cents, shipped_value_cents,
                              share_bps, variant):
    """pool = 800bps of gross subtotal; share = min(requested, engineer cap).

    provisional: the full pool share, stored when the quote is submitted.
    final:       the pool prorated by the fraction of line value that shipped,
                 stored once every line of the quote has a shipped instrument.
    """
    pool_cents = commission_pool_cents(gross_subtotal_cents)
    if variant == "provisional":
        return apply_bps(pool_cents, share_bps)
    if not gross_subtotal_cents:
        return 0
    prorated = (Decimal(pool_cents) * Decimal(share_bps) / Decimal(10000)
                * Decimal(shipped_value_cents) / Decimal(gross_subtotal_cents))
    return money(prorated)


# ---------------------------------------------------------------------------
# package_bundle_price_cents (combinatorial_nested, pinned order)
# ---------------------------------------------------------------------------

def package_bundle_price_cents(lines, package_type):
    """step 1 per-unit discount, step 2 subtotal, step 3 tier, step 4 apply.

    Only SYSTEM_PACKAGE quotes receive SYSTEM_LINE_DISCOUNT_BPS in step 1;
    INSTRUMENT_ONLY and ACCESSORY_ONLY quotes use the raw catalogue price.
    """
    subtotal = 0
    for line in lines:
        unit = line["unit_price_cents"]
        if package_type == "SYSTEM_PACKAGE":
            unit = apply_bps(unit, 10000 - SYSTEM_LINE_DISCOUNT_BPS)
        subtotal += unit * int(line.get("quantity") or 1)
    if subtotal >= TIER_HIGH_CENTS:
        tier_bps = TIER_HIGH_BPS
    elif subtotal >= TIER_MID_CENTS:
        tier_bps = TIER_MID_BPS
    else:
        tier_bps = 0
    return apply_bps(subtotal, 10000 - tier_bps)


# ---------------------------------------------------------------------------
# warranty_service_fee_cents (dual_variant)
# ---------------------------------------------------------------------------

def warranty_service_fee_cents(plan, variant):
    """provisional: the per-round bench fee, growing with each repair round.

    final: the term-scaled flat fee, round-count-independent, reading
    repair_rounds_used before the closing transition increments it.
    """
    if variant == "provisional":
        return BASE_ROUND_FEE_CENTS * (int(plan.get("repair_rounds_used") or 0) + 1)
    return money(Decimal(BASE_ROUND_FEE_CENTS)
                 * Decimal(int(plan.get("term_months") or 0))
                 / Decimal(TERM_MONTHS_BASELINE))


# ---------------------------------------------------------------------------
# instrument_inspection_verdict (combinatorial_nested)
# ---------------------------------------------------------------------------

def instrument_inspection_verdict(action_height_mm, relief_mm,
                                  intonation_offset_cents, variant):
    """Measurements are rounded half-up to 2dp *before* comparison, then folded.

    preliminary (at SETUP_COMPLETE): CONDITIONAL for any two-of-three pass.
    final (at INSPECTED): a failed intonation check is disqualifying, so a
    two-of-three unit whose failing check is intonation grades FAIL.
    """
    action_ok = (ACTION_MIN_MM <= half_up(action_height_mm, 2) <= ACTION_MAX_MM)
    relief_ok = half_up(relief_mm, 2) >= RELIEF_MIN_MM
    intonation_ok = abs(intonation_offset_cents) <= INTONATION_TOLERANCE_CENTS
    checks_passed = (1 if action_ok else 0) + (1 if relief_ok else 0) \
        + (1 if intonation_ok else 0)
    if checks_passed == 3:
        return "PASS"
    if checks_passed == 2:
        if variant == "final" and not intonation_ok:
            return "FAIL"
        return "CONDITIONAL"
    return "FAIL"


# ---------------------------------------------------------------------------
# backorder_allocation_units (waterfall_allocation)
# ---------------------------------------------------------------------------

def backorder_walk_order(backorders):
    return sorted(backorders, key=lambda bo: (bo.get("alloc_sequence") or 0,
                                              bo.get("preorder_open_at") or "",
                                              bo.get("created_at") or ""))


def overcommit_estimate_units(units_requested, pool_units):
    """provisional: each claim is measured against the whole pool on its own, so
    the estimates are explicitly permitted to sum above pool_units."""
    return min(int(units_requested), int(pool_units))


def waterfall_units_filled(backorders, pool_units):
    """final: one pass in walk order that depletes the pool exactly.

    Returns {backorder_id: granted_units}.  No fraction of a unit is allocated.
    """
    remaining = int(pool_units)
    granted = {}
    for bo in backorder_walk_order(backorders):
        take = min(int(bo.get("units_requested") or 0), remaining)
        granted[bo["id"]] = take
        remaining -= take
    return granted


# ---------------------------------------------------------------------------
# gear_exchange_restocking_fee (combinatorial_nested)
# ---------------------------------------------------------------------------

def restocking_fee_bps(reason, account_tier, days_remaining):
    base_bps = REASON_BPS.get(reason, 0)
    tier_adjust = TIER_ADJUST_BPS.get(account_tier, 0)
    days_bps = NEAR_EXPIRY_BPS if days_remaining < NEAR_EXPIRY_DAYS else 0
    return max(0, base_bps + tier_adjust + days_bps)


def gear_exchange_restocking_fee(line_total_cents, reason, account_tier,
                                 days_remaining, variant):
    """provisional (trial start): the bare reason rate.

    final (return requested): the composed effective rate (reason + tier +
    near-expiry, floored at zero) applied once against the line total.
    """
    if variant == "provisional":
        bps = REASON_BPS.get(reason, 0)
    else:
        bps = restocking_fee_bps(reason, account_tier, days_remaining)
    return apply_bps(line_total_cents, bps)


# ---------------------------------------------------------------------------
# customer_tech_support_entitlement (weighted_scoring)
# ---------------------------------------------------------------------------

def customer_tech_support_entitlement(has_active_assignment, has_warranty_in_force,
                                      purchased_instrument_count):
    if has_warranty_in_force:
        return "EXTENDED"
    if has_active_assignment and purchased_instrument_count >= MIN_PURCHASES_FOR_BASIC:
        return "BASIC"
    return "NONE"


# ---------------------------------------------------------------------------
# engineer_seniority_tier (threshold)
# ---------------------------------------------------------------------------

def engineer_seniority_tier(certified_family_count):
    if certified_family_count >= TIER_3_MIN:
        return "TIER_3", TIER_CAPS["TIER_3"]
    if certified_family_count >= TIER_2_MIN:
        return "TIER_2", TIER_CAPS["TIER_2"]
    return "TIER_1", TIER_CAPS["TIER_1"]


# ---------------------------------------------------------------------------
# quote_dependency_closure_size (topological)
# ---------------------------------------------------------------------------

def closure_from_anchors(lines, anchors):
    """Lines reachable from the anchor set by following requires_line_id edges."""
    by_id = {line["id"]: line for line in lines}
    closure = []
    seen = set()
    frontier = list(anchors)
    while frontier:
        line = frontier.pop()
        if line["id"] in seen:
            continue
        seen.add(line["id"])
        closure.append(line)
        for candidate in lines:
            if candidate.get("requires_line_id") == line["id"] \
                    and candidate["id"] not in seen:
                frontier.append(candidate)
    return closure, by_id


def dependency_closure_size(lines):
    """Size of the closure rooted at the (single) anchor line.

    A quote with no anchor line has an empty closure and size zero.
    """
    anchors = [line for line in lines if line.get("is_anchor")]
    closure, _ = closure_from_anchors(lines, anchors)
    return len(closure)


def bundle_ready(lines):
    """Every closure dependency resolves inside the quote, and every product in
    the closure whose required_family is set finds a member of that family
    inside the closure.

    Exactly one line must anchor the quote: a quote with no anchor line has
    nothing to explore from, so it can never be bundle_ready (PRD §3.2).
    """
    anchors = [line for line in lines if line.get("is_anchor")]
    if len(anchors) != 1:
        return False
    closure, _ = closure_from_anchors(lines, anchors)
    line_ids = {line["id"] for line in lines}
    for line in closure:
        prereq = line.get("requires_line_id")
        if prereq is not None and prereq not in line_ids:
            return False
    families = {line.get("product_family") for line in closure}
    for line in closure:
        required = line.get("required_family")
        if required and required not in families:
            return False
    return True


def dependency_edges(lines):
    """requires_line_id edges restricted to lines of this quote."""
    line_ids = {line["id"] for line in lines}
    edges = {}
    for line in lines:
        prereq = line.get("requires_line_id")
        edges[line["id"]] = prereq if prereq in line_ids else None
    return edges


def has_cycle(lines):
    """True when requires_line_id edges among the quote's lines double back."""
    edges = dependency_edges(lines)
    state = {}

    def visit(node):
        state[node] = 1
        nxt = edges.get(node)
        if nxt is not None:
            if state.get(nxt) == 1:
                return True
            if state.get(nxt) is None and visit(nxt):
                return True
        state[node] = 2
        return False

    for node in edges:
        if state.get(node) is None and visit(node):
            return True
    return False


# ---------------------------------------------------------------------------
# days_remaining (PRD §2.6): whole days from the clock to the trial end,
# rounded up, floored at zero.
# ---------------------------------------------------------------------------

def days_remaining(trial_end_date, clock_now):
    delta = (trial_end_date - clock_now).total_seconds() / 86400.0
    return max(0, int(math.ceil(round(delta, 6))))