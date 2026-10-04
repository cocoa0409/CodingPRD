"""The pinned calculation rules.

Every monetary result is an exact whole number of cents; rates are applied
with Decimal and round half up exactly once, at the point the rule names.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- order_gross_total -----------------------------------------------------
MIX_FACTOR = {
    "DIAGNOSTIC_WEIGHTED": Decimal("1.0075"),
    "TOOL_STORAGE": Decimal("1.0150"),
    "POWER_TOOLS": Decimal("1.0025"),
}

# --- finance_charge_accrual ------------------------------------------------
WEEKS_PER_YEAR = 52
TIER_BOUNDARY_LOW = 50000
TIER_BOUNDARY_HIGH = 200000
RATE_LOW = Decimal("0.1560")
RATE_MID = Decimal("0.1820")
RATE_HIGH = Decimal("0.2080")

# --- credit_decision_score -------------------------------------------------
SCORE_BASE = 40
MONTHS_IN_TRADE_WEIGHT = Decimal("0.5")
MONTHS_CAP = 120
DELINQUENCY_PENALTY = 9
EMPLOYMENT_BONUS = 12
REQUESTED_KIND_BONUS = 4
LIMIT_TIER_BOUNDARY = 500000
HIGH_TIER_MULTIPLIER = Decimal("1.05")
LOW_TIER_MULTIPLIER = Decimal("1.00")
SCORE_FLOOR = 1
SCORE_CEILING = 100

# --- credit_decision_limit -------------------------------------------------
T1_MAX = 40
T2_MAX = 60
T1_RATE = 750
T2_RATE = 500
T3_RATE = 250

# --- fiscal caps -----------------------------------------------------------
CREDIT_ABSOLUTE_CAP_CENTS = 2000000
FRANCHISEE_RESALE_FEE_CAP_CENTS = 900000

# --- route_replenishment_allocation ---------------------------------------
LEAD_CATEGORY = {
    "DIAGNOSTIC_WEIGHTED": "DIAGNOSTICS",
    "TOOL_STORAGE": "TOOL_STORAGE",
    "POWER_TOOLS": "POWER_TOOLS",
}

# --- launch_allocation_plan ------------------------------------------------
TIER_WEIGHT = {"A": 3, "B": 2, "C": 1}
RISK_MEDIUM_THRESHOLD = 60
RISK_LOW_THRESHOLD = 120

# --- warranty_replacement_charge ------------------------------------------
CAP_RATE = Decimal("0.40")
CREDIT_RATE = Decimal("0.60")

# --- minimum_payment_due ---------------------------------------------------
MIN_TIER_BOUNDARY = 25000
MID_TIER_BOUNDARY = 150000
MIN_TIER_PCT = Decimal("0.05")
MID_TIER_PCT = Decimal("0.10")
MAX_TIER_PCT = Decimal("0.20")
FLAT_MINIMUM_CENTS = 2500

# --- lease_amortization ----------------------------------------------------
LEASE_ANNUAL_RATE = Decimal("0.2400")
MONTHS_PER_YEAR = 12
DELINQUENT_UPLIFT = Decimal("1.25")

# --- charge_off_week -------------------------------------------------------
CHARGE_OFF_WEEKS = 26

# --- reopening_fee ---------------------------------------------------------
FEE_NOT_ENROLLED = 900000
FEE_ENROLLED = 650000
FEE_CERTIFIED = 250000
POINTS_PER_DISCOUNT_UNIT = 10
DISCOUNT_PER_UNIT_CENTS = 15000
POINTS_CAP = 60
FEE_FLOOR_CENTS = 200000

# --- franchisee_training_progress -----------------------------------------
CERTIFICATION_THRESHOLD = 40

CENTS = Decimal(1)


def round_half_up(value):
    """Round a Decimal to a whole number of cents, half up."""
    return int(Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP))


def floor_rate(value, rate):
    """floor(value * rate) in exact cents."""
    return int((Decimal(value) * Decimal(rate)).to_integral_value(rounding="ROUND_FLOOR"))


# --------------------------------------------------------------------------
# Order pricing
# --------------------------------------------------------------------------

def line_amount(unit_price_cents, quantity, mix_profile):
    factor = MIX_FACTOR.get(mix_profile, Decimal("1"))
    return round_half_up(Decimal(unit_price_cents) * Decimal(quantity) * factor)


def order_gross_total(lines, mix_profile):
    """Round each line independently, then sum — the pinned rounding order."""
    total = 0
    for line in lines:
        total += line_amount(line.get("unit_price_cents", 0), line.get("quantity", 0), mix_profile)
    return total


def order_financing_variant(order, gross_total, approved_claim_allocations, settled):
    """PROVISIONAL (gross) before delivery, FINAL (gross minus approvals) after."""
    if settled:
        return order.get("financed_principal_cents", gross_total)
    status = order.get("order_status")
    if status in ("DRAFT", "CONFIRMED"):
        return gross_total
    return gross_total - sum(approved_claim_allocations)


# --------------------------------------------------------------------------
# Credit adjudication
# --------------------------------------------------------------------------

def credit_decision_score(application):
    base = Decimal(SCORE_BASE)
    months = min(application.get("months_in_trade", 0) or 0, MONTHS_CAP)
    base += MONTHS_IN_TRADE_WEIGHT * Decimal(months)
    base -= Decimal(DELINQUENCY_PENALTY) * Decimal(application.get("prior_delinquency_count", 0) or 0)
    if application.get("employment_verified"):
        base += EMPLOYMENT_BONUS
    if application.get("requested_kind") == "LEASE":
        base += REQUESTED_KIND_BONUS
    if (application.get("requested_limit_cents", 0) or 0) >= LIMIT_TIER_BOUNDARY:
        base = base * HIGH_TIER_MULTIPLIER
    else:
        base = base * LOW_TIER_MULTIPLIER
    score = int(math.floor(base))
    return max(SCORE_FLOOR, min(SCORE_CEILING, score))


def credit_decision_limit(decision_score, requested_limit_cents):
    """Marginal tiering on the approved score, capped by the requested amount."""
    if decision_score <= T1_MAX:
        amount = T1_RATE * decision_score
    elif decision_score <= T2_MAX:
        amount = T1_RATE * T1_MAX + T2_RATE * (decision_score - T1_MAX)
    else:
        amount = (T1_RATE * T1_MAX
                  + T2_RATE * (T2_MAX - T1_MAX)
                  + T3_RATE * (decision_score - T2_MAX))
    return min(amount, requested_limit_cents)


# --------------------------------------------------------------------------
# Accrual, amortisation, minimum due
# --------------------------------------------------------------------------

def accrual_rate(basis):
    if basis < TIER_BOUNDARY_LOW:
        return RATE_LOW
    if basis < TIER_BOUNDARY_HIGH:
        return RATE_MID
    return RATE_HIGH


def finance_charge_amount(basis):
    """One rounding, at the very end of the formula."""
    return round_half_up(Decimal(basis) * accrual_rate(basis) / Decimal(WEEKS_PER_YEAR))


def lease_installment(principal_cents, term_months):
    if not term_months:
        return 0
    monthly_rate = LEASE_ANNUAL_RATE / Decimal(MONTHS_PER_YEAR)
    factor = (Decimal(1) + monthly_rate) ** (-int(term_months))
    raw = Decimal(principal_cents) * monthly_rate / (Decimal(1) - factor)
    return round_half_up(raw)


def lease_amortization(principal_cents, term_months, account_status):
    rounded = lease_installment(principal_cents, term_months)
    if account_status == "DELINQUENT":
        return round_half_up(Decimal(rounded) * DELINQUENT_UPLIFT)
    return rounded


def minimum_payment_due(current_balance_cents, account_status, is_lease, installment_due_cents):
    if is_lease:
        return installment_due_cents
    opening = current_balance_cents
    if opening < MIN_TIER_BOUNDARY:
        pct = MIN_TIER_PCT
    elif opening < MID_TIER_BOUNDARY:
        pct = MID_TIER_PCT
    else:
        pct = MAX_TIER_PCT
    due = max(FLAT_MINIMUM_CENTS, round_half_up(Decimal(opening) * pct))
    if account_status == "DELINQUENT":
        due = current_balance_cents
    return due


def charge_off_due(account_status_changed_week, current_week):
    """Half-open window anchored on the delinquency anniversary (inclusive)."""
    from datetime import timedelta
    effective = account_status_changed_week + timedelta(weeks=CHARGE_OFF_WEEKS)
    return effective <= current_week


# --------------------------------------------------------------------------
# Payment allocation
# --------------------------------------------------------------------------

def payment_allocation(amount_cents, open_charges):
    """Oldest-accrual-first, exact: returns (charge_applied, principal_reduction, takes)."""
    remaining = amount_cents
    takes = []
    for charge in open_charges:
        if remaining <= 0:
            break
        outstanding = charge["charge_amount_cents"] - charge["collection_applied_cents"]
        take = min(remaining, outstanding)
        if take <= 0:
            continue
        takes.append((charge["id"], take))
        remaining -= take
    applied = amount_cents - remaining
    return applied, remaining, takes


# --------------------------------------------------------------------------
# Replenishment fill
# --------------------------------------------------------------------------

def replenishment_priority(line, mix_profile, product):
    lead = LEAD_CATEGORY.get(mix_profile)
    band = 0 if product.get("category") == lead else 1
    return (band, product.get("unit_cost_cents", 0), line["line_index"])


def route_replenishment_allocation(ceiling_cents, requested_lines, products, mix_profile):
    """Waterfall fill in the pinned three-part priority order."""
    ranked = sorted(
        requested_lines,
        key=lambda entry: replenishment_priority(entry, mix_profile, products[entry["product_id"]]),
    )
    remaining = ceiling_cents
    ordered = {}
    for entry in ranked:
        product = products[entry["product_id"]]
        unit_cost = product.get("unit_cost_cents", 0)
        if unit_cost <= 0:
            affordable = entry["requested_qty"]
        else:
            affordable = remaining // unit_cost
        qty = min(entry["requested_qty"], affordable)
        ordered[entry["line_index"]] = qty
        remaining -= qty * unit_cost
    ordered_lines = []
    deferred_lines = []
    for entry in requested_lines:
        qty = ordered.get(entry["line_index"], 0)
        unit_cost = products[entry["product_id"]].get("unit_cost_cents", 0)
        ordered_lines.append({
            "product_id": entry["product_id"],
            "ordered_qty": qty,
            "line_index": entry["line_index"],
            "unit_cost_cents": unit_cost,
        })
        if qty < entry["requested_qty"]:
            deferred_lines.append({
                "product_id": entry["product_id"],
                "line_index": entry["line_index"],
                "deferred_qty": entry["requested_qty"] - qty,
            })
    ordered_cost = sum(line["ordered_qty"] * line["unit_cost_cents"] for line in ordered_lines)
    return ordered_lines, deferred_lines, ordered_cost, len(deferred_lines) == 0


def mixed_inventory_plan(pledges, position_lookup):
    """Conserve units across pledges: a unit is claimable by at most one pledge."""
    ordered = sorted(pledges, key=lambda p: (p.get("line_index", 0), p.get("created_at") or ""))
    claimed = {}
    results = {}
    for pledge in ordered:
        total = 0
        for share in pledge.get("pledged_lines", []):
            product_id = share.get("product_id")
            position = position_lookup(pledge.get("route_id"), product_id)
            if position is None:
                continue
            taken = claimed.get(product_id, 0)
            available = max(0, position.get("remaining_qty", 0) - taken)
            sustained = min(share.get("qty", 0), available)
            claimed[product_id] = taken + sustained
            total += sustained * position.get("unit_cost_cents", 0)
        results[pledge["id"]] = total
    return results


# --------------------------------------------------------------------------
# Launch allocation
# --------------------------------------------------------------------------

def launch_priority_score(route, open_order_count):
    weight = TIER_WEIGHT.get(route.get("route_tier"), 1)
    points = route.get("territory_points", 0) or 0
    return (Decimal(weight) * Decimal(points)) / Decimal(1 + open_order_count)


def launch_risk_band(priority_score):
    if priority_score >= RISK_LOW_THRESHOLD:
        return "LOW"
    if priority_score >= RISK_MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "HIGH"


def launch_allocation_plan(routes_with_scores, total_launch_qty):
    """Floor shares, then hand out the leftover one unit at a time."""
    total_weight = sum(score for _, score in routes_with_scores)
    shares = {}
    fractions = {}
    for route, score in routes_with_scores:
        if total_weight > 0:
            exact = Decimal(total_launch_qty) * score / total_weight
        else:
            exact = Decimal(0)
        floored = int(exact.to_integral_value(rounding="ROUND_FLOOR"))
        shares[route["id"]] = floored
        fractions[route["id"]] = exact - floored
    leftover = total_launch_qty - sum(shares.values())
    ranked = sorted(
        [route for route, _ in routes_with_scores],
        key=lambda r: (-fractions[r["id"]], r.get("created_at") or ""),
    )
    index = 0
    while leftover > 0 and ranked:
        shares[ranked[index % len(ranked)]["id"]] += 1
        leftover -= 1
        index += 1
    return shares


# --------------------------------------------------------------------------
# Warranty and resale
# --------------------------------------------------------------------------

def warranty_charges(line, product, elapsed_months, warranty_months):
    inside = elapsed_months < warranty_months
    if inside:
        return 0
    return min(line.get("unit_price_cents", 0),
               floor_rate(product.get("unit_cost_cents", 0), CAP_RATE))


def warranty_credit_amount(line, product, claim_kind, claim_status):
    if claim_kind == "CLAIM" and claim_status == "APPROVED":
        return min(line.get("unit_price_cents", 0),
                   floor_rate(product.get("unit_cost_cents", 0), CREDIT_RATE))
    return 0


def warranty_principal_allocation(claim_kind, replacement_charge_cents,
                                  warranty_credit_amount_cents, target_principal):
    """CHARGE_BASIS adds principal; CREDIT_BASIS credits it away, floored at 0."""
    if claim_kind == "CLAIM":
        return replacement_charge_cents
    allocated = warranty_credit_amount_cents
    return min(allocated, target_principal)


def reopening_fee(buyer_training_status, trained_points):
    if buyer_training_status == "NOT_ENROLLED":
        base = FEE_NOT_ENROLLED
    elif buyer_training_status == "ENROLLED":
        base = FEE_ENROLLED
    else:
        return FEE_CERTIFIED
    points = min(trained_points or 0, POINTS_CAP)
    discount = (points // POINTS_PER_DISCOUNT_UNIT) * DISCOUNT_PER_UNIT_CENTS
    return max(FEE_FLOOR_CENTS, base - discount)


def franchisee_training_progress(training_points):
    return "CERTIFIED" if (training_points or 0) >= CERTIFICATION_THRESHOLD else "ENROLLED"
