"""Every calculation rule of scaffolding Table 3.

All monetary arithmetic runs on ``decimal.Decimal`` with string constants so no
binary floating point error can reach a cent; ``rhu`` is round-half-up.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from db import parse_iso

# -- constants (scaffold Table 3) -------------------------------------------

PRIORITY_BASE = {
    "HOMELESS_SHELTER": 70,
    "DOMESTIC_VIOLENCE_SHELTER": 83,
    "YOUTH_OUTREACH": 52,
    "VETERAN_OUTREACH": 61,
    "DISASTER_RELIEF": 95,
    "COMMUNITY_HEALTH_CLINIC": 20,
}
REGION_ADJUSTMENT = {
    "NORTHEAST": 3,
    "SOUTHEAST": 0,
    "MIDWEST": 6,
    "SOUTHWEST": 2,
    "WEST": -2,
}
REQUIRED_VERIFICATION_POINTS = 4
ACCESS_CAP = 20
RECIPIENT_DIVISOR = 1000
APPROVAL_MINIMUM = 40

DONATION_UPLIFT = Decimal("0.70")
DONATION_UPLIFT_RATE = Decimal("0.70")
DONATION_OFFSET_RATE = Decimal("0.05")
DONATION_BUILD_RATE = Decimal("0.70")
DONATION_PROVENANCE_DISCOUNT = Decimal("0.50")
LIABILITY_FLOOR_CENTS = 0
LIABILITY_CEILING_CENTS = 100000
ADDON_T1_MAX = 5000
ADDON_T2_MAX = 15000

FABRIC_BASE = {
    "ATHLETIC_SOCK": 40,
    "UNDERGARMENT": 45,
    "APPAREL_TOP": 30,
    "SLEEP_ACCESSORY": 20,
}
REUSE_POINTS = 20
CHANNEL_POINTS = {"DONATION_ONLY": 10, "DUAL_CHANNEL": 0}
ACTIVATION_MINIMUM = 60

PRIORITY_POINTS = {"EMERGENCY": 40, "CRITICAL": 30, "HIGH": 20, "MODERATE": 10}
FIT_CAP = 30
NEED_CAP = 25
ESSENTIAL_CAP = 10
RECENCY_POINTS = 5
RECENCY_WINDOW_DAYS = 5

BASE_WEIGHT = Decimal("1.00")
INDEX_WEIGHT = Decimal("0.35")
ESSENTIAL_WEIGHT = Decimal("0.60")
LIQUIDITY_CAP_DEFAULT = 10
LIQUIDITY_CAP_MIN = 1
LIQUIDITY_CAP_MAX = 50

SUBSTANTIATION_FLOOR = Decimal("1.0000")
CAPACITY_SHARE_CAP = 12000

CLEARANCE_WEIGHT = 50
CYCLE_TIME_CEILING_DAYS = 10
CYCLE_TIME_WEIGHT = Decimal("2.5")
RECEIPT_LOGGING_WEIGHT = 15
EXCEPTION_PENALTY = 10
BAND_EXEMPLARY = 85
BAND_SATISFACTORY = 60
BAND_MONITORED = 40

SAMPLE_RATIO = Decimal("0.25")
SAMPLE_PER_DISTRIBUTION_CAP = 40

# Status sets used by the two unit ledgers and the currency ledger
PROVISIONAL_ORDER_STATUSES = {
    "CREATED", "PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED", "REFUNDED",
}
FINAL_ORDER_STATUSES = {"PAID", "DONATION_SATISFIED"}
CURRENCY_ORDER_STATUSES = {
    "PAID", "DONATION_SATISFIED", "PARTIALLY_REFUNDED", "REFUNDED",
}
COUNTED_ALLOCATION_STATUSES = {"APPROVED", "SHIPPED", "PARTIALLY_RECEIVED", "RECEIVED"}
TERMINAL_ALLOCATION_STATUSES = {"CANCELLED", "REVERSED"}


def rhu(value, places=0):
    """Round half up to ``places`` decimal places, returning an int when places=0."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def clamp(value, low, high):
    return max(low, min(high, value))


# -- registry / need score ---------------------------------------------------

def registry_verified(registry_id, ein):
    """true when registry_id is AA-CHR-DDDDDD and ein is nine digits."""
    if not isinstance(registry_id, str) or not isinstance(ein, str):
        return False
    if len(registry_id) != 13:
        return False
    if registry_id[0:2].isupper() is False or not registry_id[0:2].isalpha():
        return False
    if registry_id[2] != "-" or registry_id[6] != "-":
        return False
    if registry_id[3:6] != "CHR":
        return False
    if not registry_id[7:].isdigit() or len(registry_id[7:]) != 6:
        return False
    return len(ein) == 9 and ein.isdigit()


def need_score(partner, points=None):
    """calculations.need_score — threshold variant on verification points."""
    if points is None:
        points = 0
    base = PRIORITY_BASE.get(partner.get("partner_type"), 0)
    base += REGION_ADJUSTMENT.get(partner.get("operating_region"), 0)
    if points >= REQUIRED_VERIFICATION_POINTS:
        base -= 5
    recipients = partner.get("unduplicated_recipients_per_facility") or 0
    access_component = min(ACCESS_CAP, recipients // RECIPIENT_DIVISOR)
    return clamp(base + access_component, 0, 100)


# -- product design ----------------------------------------------------------

def product_attribute_weight(product_kind, is_reusable, design_channel):
    score = FABRIC_BASE.get(product_kind, 0)
    if is_reusable:
        score += REUSE_POINTS
    score += CHANNEL_POINTS.get(design_channel, 0)
    return clamp(score, 0, 100)


def design_variant_code(donation_eligible, design_channel):
    if not donation_eligible:
        return "none"
    if design_channel == "DONATION_ONLY":
        return "donation_specific"
    return "retail_dual"


def obligation_units(product, donation_eligible):
    if not donation_eligible:
        return 0
    return product.get("approved_donation_ratio_units") or 0


def donation_unit_cost(product):
    """calculations.donation_unit_cost — min applied last over rounded terms.

    NOTE: the uplift term is ``unit_cost_cents * 0.70``; both documents' worked
    literals (1150 -> 805, 1155 -> 809, dual 2300/3300 -> 1445) pin this, while
    one PRD sentence describes it as "one plus seventy hundredths".
    """
    unit_cost = Decimal(product.get("unit_cost_cents") or 0)
    retail_price = Decimal(product.get("retail_price_cents") or 0)
    donation_uplift_cents = rhu(unit_cost * DONATION_UPLIFT_RATE)
    retail_offset_cents = rhu(retail_price * DONATION_OFFSET_RATE)
    if product.get("design_channel") == "DUAL_CHANNEL":
        net_upcharge_cents = max(0, donation_uplift_cents - retail_offset_cents)
    else:
        net_upcharge_cents = donation_uplift_cents
    return min(int(unit_cost), net_upcharge_cents)


def mixed_supply_unit_liability(product, unit_obligation_cost_cents, unit_value_cents):
    """calculations.mixed_supply_unit_liability — the wider per-unit figure."""
    unit_value = Decimal(unit_value_cents)
    donation_build_cost_cents = rhu(unit_value * (Decimal(1) + DONATION_BUILD_RATE))
    provenance_discount_cents = rhu(
        Decimal(donation_build_cost_cents) * DONATION_PROVENANCE_DISCOUNT
    )
    if donation_build_cost_cents <= provenance_discount_cents:
        return unit_obligation_cost_cents
    gap = max(0, donation_build_cost_cents - provenance_discount_cents)
    raw = unit_obligation_cost_cents + gap
    return min(LIABILITY_CEILING_CENTS, max(LIABILITY_FLOOR_CENTS, raw))


def addon_pool(rows):
    """Recalculate the add-on requirement vector.

    The tier divisor is selected on ``base_units`` BEFORE the surcharge exists,
    and the surcharge is never netted back out of the requirement.
    """
    base_units = 0
    for alloc in rows:
        if alloc.get("allocation_kind") != "ALLOCATION":
            continue
        if alloc.get("status") in COUNTED_ALLOCATION_STATUSES:
            base_units += alloc.get("allocated_units") or 0
    if base_units <= ADDON_T1_MAX:
        tier_divisor = 100
    elif base_units <= ADDON_T2_MAX:
        tier_divisor = 200
    else:
        tier_divisor = 400
    surcharge_units = int(math.ceil(Decimal(base_units) / Decimal(tier_divisor)))
    return {
        "base_units": base_units,
        "tier_divisor": tier_divisor,
        "surcharge_units": surcharge_units,
    }


# -- liability ledgers -------------------------------------------------------

def _line_in_season(line, season_id):
    return line.get("impact_season_id") == season_id


def provisional_liability_units(db, product_id, season_id):
    total = 0
    for line in db.sales_order_lines.values():
        if line["donation_product_id"] != product_id:
            continue
        if not _line_in_season(line, season_id):
            continue
        product = db.product(product_id)
        if not product or product.get("obligation_model") != "AT_SALE":
            continue
        variant = db.product_line(line["donation_product_line_id"])
        if not variant or not variant.get("donation_eligible"):
            continue
        order = db.order(line["sales_order_id"])
        if not order or order["status"] not in PROVISIONAL_ORDER_STATUSES:
            continue
        total += (line.get("quantity") or 0) * (variant.get("obligation_units") or 0)
    return total


def final_liability_units(db, product_id, season_id):
    total = 0
    for line in db.sales_order_lines.values():
        if line["donation_product_id"] != product_id:
            continue
        if not _line_in_season(line, season_id):
            continue
        variant = db.product_line(line["donation_product_line_id"])
        if not variant or not variant.get("donation_eligible"):
            continue
        order = db.order(line["sales_order_id"])
        if not order or order["status"] not in FINAL_ORDER_STATUSES:
            continue
        total += (line.get("quantity") or 0) * (variant.get("obligation_units") or 0)
    return total


def donation_credit_ledger(db, product_id, season_id):
    """calculations.donation_credit_ledger — summed from per-line rounded cents."""
    product = db.product(product_id)
    unit_cost = Decimal((product or {}).get("unit_cost_cents") or 0)
    donation_cost_cents = 0
    donation_credit_units = 0
    obligation_units_sum = 0
    for line in db.sales_order_lines.values():
        if line["donation_product_id"] != product_id:
            continue
        if not _line_in_season(line, season_id):
            continue
        variant = db.product_line(line["donation_product_line_id"])
        if not variant or not variant.get("donation_eligible"):
            continue
        order = db.order(line["sales_order_id"])
        if not order or order["status"] not in CURRENCY_ORDER_STATUSES:
            continue
        quantity = line.get("quantity") or 0
        # PRD §3.5: "Each line's donation cost is its quantity multiplied by the
        # product's manufacturing cost multiplied by one plus seventy hundredths,
        # rounded half up to whole cents, and the ledger's `donation_cost_cents`
        # is the sum of those rounded line costs." The rounding happens once per
        # line (the §2.8 7371-vs-7370 worked example pins the per-line order).
        donation_cost_cents += rhu(Decimal(quantity) * unit_cost * (Decimal(1) + DONATION_UPLIFT))
        donation_credit_units += quantity
        obligation_units_sum += variant.get("obligation_units") or 0
    return {
        "donation_cost_cents": donation_cost_cents,
        "donation_credit_units": donation_credit_units,
        "obligation_units": obligation_units_sum,
    }


def accredited_liability_cents(db, product_id, season_id):
    """obligation_cost_cents and funding_shortfall_cents for the ledger."""
    product = db.product(product_id)
    liability = None
    for row in db.donation_liabilities.values():
        if row["donation_product_id"] == product_id and row["impact_season_id"] == season_id:
            liability = row
            break
    unit_obligation_cost_cents = 0
    if product:
        lines = [l for l in db.product_lines(product_id)]
        if lines:
            unit_obligation_cost_cents = lines[0].get("unit_obligation_cost_cents") or 0
    ledger = donation_credit_ledger(db, product_id, season_id)
    obligation_cost_cents = ledger["obligation_units"] * unit_obligation_cost_cents
    return {
        "obligation_cost_cents": obligation_cost_cents,
        "funding_shortfall_cents": max(0, obligation_cost_cents - ledger["donation_cost_cents"]),
        "recorded_liability_cents": obligation_cost_cents,
    }


# -- refunds -----------------------------------------------------------------

def effective_unit_refund_cents(unit_price_cents, line_discount_cents):
    """The discounted effective unit price, rounded half up once.

    Both documents' worked literals pin this as ``unit_price - line_discount``
    (1800 with a 500-cent discount refunds 1300 per unit, 2600 for two units).
    """
    return rhu(Decimal(unit_price_cents) - Decimal(line_discount_cents))


def return_refund_amount(line, requested_units):
    unit_refund = effective_unit_refund_cents(
        line.get("unit_price_cents") or 0, line.get("line_discount_cents") or 0
    )
    return unit_refund * int(requested_units)


# -- ranking -----------------------------------------------------------------

def partner_rank_score(partner, priority_tier, allocation_fit_pct, essential_units,
                       days_since_last_capacity_receipt):
    priority_component = PRIORITY_POINTS.get(priority_tier, 0)
    fit_component = min(FIT_CAP, int(allocation_fit_pct) // 10)
    need_component = min(NEED_CAP, int(partner.get("need_score") or 0) // 10)
    essential_component = min(ESSENTIAL_CAP, int(essential_units))
    if days_since_last_capacity_receipt is not None and 0 < days_since_last_capacity_receipt <= RECENCY_WINDOW_DAYS:
        capacity_recency_component = RECENCY_POINTS
    else:
        capacity_recency_component = 0
    return clamp(
        priority_component + fit_component + need_component
        + essential_component + capacity_recency_component,
        0, 100,
    )


def rank_sort_key(db, allocation):
    partner = db.partner(allocation.get("giving_partner_id")) or {}
    return (
        -(allocation.get("rank_score") or 0),
        -(partner.get("need_score") or 0),
        -(partner.get("claim_attributed_units") or 0),
        allocation.get("created_at") or "",
    )


def weighted_allocation(partner_rows, liquidity_cap, baseline_units, demand_units, pool_units):
    """calculations.weighted_allocation — two-stage waterfall with largest remainder.

    A slot's position is 1-based (the scaffold's worked literal is reproducible
    only under the 1-based reading, and its note fixes the assignment order).
    """
    cap = int(liquidity_cap)
    slots = []
    for r in range(1, cap + 1):
        if r % 3 == 0:
            slots.append(("essential", Decimal(pool_units) * ESSENTIAL_WEIGHT))
        elif r % 2 == 0:
            slots.append(("demand", Decimal(demand_units) * INDEX_WEIGHT))
        else:
            slots.append(("baseline", Decimal(baseline_units) * BASE_WEIGHT))

    total_weight = sum(w for _, w in slots)
    per_partner = {}
    for (kind, weight), winner in zip(slots, partner_rows):
        entry = per_partner.setdefault(winner["id"], Decimal(0))
        per_partner[winner["id"]] = entry + weight

    if total_weight == 0:
        return []

    floors = {}
    remainders = {}
    for pid, aggregate in per_partner.items():
        exact = Decimal(cap) * aggregate / total_weight
        floor_value = int(exact // 1)
        floors[pid] = floor_value
        remainders[pid] = exact - floor_value

    leftover = cap - sum(floors.values())

    partner_by_id = {p["id"]: p for p in partner_rows}
    winner_order = sorted(
        per_partner.keys(),
        key=lambda pid: (-remainders[pid], (partner_by_id.get(pid) or {}).get("legal_name") or ""),
    )

    results = []
    for index, pid in enumerate(winner_order):
        units = floors[pid] + (1 if index < leftover else 0)
        results.append((pid, units, float(remainders[pid]), float(per_partner[pid])))
    return results


def attributed_percentages(db, partners, total_units):
    """1-decimal shares with the residual folded into the last partner.

    Last partner order: descending claim_attributed_units, ascending legal_name.
    """
    ordered = sorted(
        partners,
        key=lambda p: (-(p.get("claim_attributed_units") or 0), p.get("legal_name") or ""),
    )
    if not ordered:
        return {}, 0.0
    if total_units <= 0:
        result = {p["id"]: 0.0 for p in ordered}
        return result, 0.0
    shares = {}
    running = Decimal(0)
    for partner in ordered[:-1]:
        share = (Decimal(partner.get("claim_attributed_units") or 0) * Decimal(100)
                 / Decimal(total_units))
        rounded = float(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        shares[partner["id"]] = rounded
        running += Decimal(str(rounded))
    last = ordered[-1]
    shares[last["id"]] = float((Decimal(100) - running).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return shares, 100.0


# -- claims ------------------------------------------------------------------

def claim_substantiation(db, claim):
    season_id = claim.get("impact_season_id")
    partner_id = claim.get("partner_id")
    stated = claim.get("stated_donation_units") or 0
    multiplier = claim.get("winback_multiplier") or 1
    required_units = stated * multiplier

    shipped_units = 0
    for dist in db.donation_distributions.values():
        if dist.get("impact_season_id") != season_id:
            continue
        if dist.get("status") == "VOIDED":
            continue
        alloc = db.allocation(dist.get("allocation_id"))
        if not alloc or alloc.get("giving_partner_id") != partner_id:
            continue
        shipped_units += dist.get("shipped_units") or 0

    capacity_committed_units = 0
    for alloc in db.donation_allocations.values():
        if alloc.get("impact_season_id") != season_id:
            continue
        if alloc.get("giving_partner_id") != partner_id:
            continue
        if alloc.get("allocation_kind") != "ALLOCATION":
            continue
        if alloc.get("status") not in COUNTED_ALLOCATION_STATUSES:
            continue
        capacity_committed_units += alloc.get("allocated_units") or 0
    capacity_committed_units = min(CAPACITY_SHARE_CAP, capacity_committed_units)

    carried_in_units = 0
    liability = find_liability(db, claim.get("donation_product_id"), season_id)
    if liability:
        carried_in_units = liability.get("carried_in_units") or 0

    substantiated = shipped_units + capacity_committed_units + carried_in_units
    if required_units <= 0:
        ratio = None
    else:
        ratio = Decimal(substantiated) / Decimal(required_units)
        ratio = float(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    return {
        "shipped_units": shipped_units,
        "capacity_committed_units": capacity_committed_units,
        "carried_in_units": carried_in_units,
        "required_units": required_units,
        "substantiated_donation_units": substantiated,
        "substantiated_ratio_value": ratio,
        "substantiated": ratio is not None and Decimal(str(ratio)) >= SUBSTANTIATION_FLOOR,
    }


def find_liability(db, product_id, season_id):
    for row in db.donation_liabilities.values():
        if row["donation_product_id"] == product_id and row["impact_season_id"] == season_id:
            return row
    return None


def required_stated_units(db, product_id, season_id):
    total = 0
    for claim in db.marketing_claims.values():
        if claim.get("donation_product_id") != product_id:
            continue
        if claim.get("impact_season_id") != season_id:
            continue
        if claim.get("status") == "REVOKED":
            continue
        total += (claim.get("stated_donation_units") or 0) * (claim.get("winback_multiplier") or 1)
    return total


# -- audit / grading ---------------------------------------------------------

def _audit_distributions(db, season_id, window_end=None, window_start=None):
    """Distributions of the season, excluding VOIDED rows."""
    rows = []
    for dist in db.donation_distributions.values():
        if dist.get("impact_season_id") != season_id:
            continue
        if dist.get("status") == "VOIDED":
            continue
        rows.append(dist)
    return rows


def audit_verified(db, audit, season):
    """Verified shipped/received figures under the audit kind's own window."""
    rows = _audit_distributions(db, season["id"])
    if audit.get("audit_kind") == "PARTNER_PERFORMANCE":
        window_end = parse_iso(season["ends_at"])
    else:
        window_end = parse_iso(audit.get("finalized_at")) if audit.get("finalized_at") else db.now()
    shipped = 0
    received = 0
    for dist in rows:
        shipped += dist.get("shipped_units") or 0
        received_at = dist.get("received_at")
        if dist.get("status") == "VOIDED":
            continue
        if received_at and parse_iso(received_at) > window_end:
            continue
        received += dist.get("received_units") or 0
    return shipped, received


def unit_clearance_rate(shipped_units_verified, received_units_verified):
    if not shipped_units_verified:
        return None
    ratio = Decimal(received_units_verified) / Decimal(shipped_units_verified)
    return float(ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def computed_sample_size(total_distributions, critical_distributions):
    if total_distributions <= 0 and critical_distributions <= 0:
        return 0
    ratio_floor = int(math.ceil(Decimal(SAMPLE_RATIO) * Decimal(critical_distributions)))
    per_dist_floor = int(math.ceil(
        Decimal(critical_distributions) / Decimal(SAMPLE_PER_DISTRIBUTION_CAP)))
    return min(total_distributions, max(ratio_floor, per_dist_floor))


def partner_receipt_logged_ratio(db, partner_id, season_id):
    numerator = 0
    denominator = 0
    for dist in db.partner_distributions(partner_id):
        if dist.get("impact_season_id") != season_id:
            continue
        if dist.get("status") in ("VOIDED", "WRITTEN_OFF", "DISCREPANCY_CLAIMED"):
            continue
        if (dist.get("received_units") or 0) > 0:
            denominator += 1
            if dist.get("received_at"):
                numerator += 1
    if denominator == 0:
        return None
    return min(1.0, Decimal(numerator) / Decimal(denominator))


def partner_completed_distribution_count(db, partner_id, season_id):
    count = 0
    for dist in db.partner_distributions(partner_id):
        if dist.get("impact_season_id") != season_id:
            continue
        if dist.get("status") == "COMPLETED":
            count += 1
    return count


def grade_for_total(scorecard_total):
    if scorecard_total >= BAND_EXEMPLARY:
        return "EXEMPLARY"
    if scorecard_total >= BAND_SATISFACTORY:
        return "SATISFACTORY"
    if scorecard_total >= BAND_MONITORED:
        return "MONITORED"
    return "PROBATION"


_BAND_ORDER = ["PROBATION", "MONITORED", "SATISFACTORY", "EXEMPLARY"]


def one_band_lower(grade):
    index = _BAND_ORDER.index(grade)
    return _BAND_ORDER[max(0, index - 1)]


def partner_performance_grade(db, partner, audit, season):
    """calculations.partner_performance_grade — weighted scorecard, floored."""
    shipped, received = audit_verified(db, audit, season)
    clearance = unit_clearance_rate(shipped, received)
    # PRD §3.9: "The clearance term is the audit's four-decimal rounded clearance
    # rate multiplied by fifty — rounded first, weighted second."
    clearance_score = Decimal(0) if clearance is None else Decimal(
        str(rhu(Decimal(str(clearance)) * Decimal(CLEARANCE_WEIGHT))))

    avg_days = partner.get("avg_distribution_completion_days")
    cycle_time_score = None
    if avg_days is not None:
        cycle_time_score = (Decimal(CYCLE_TIME_CEILING_DAYS) - Decimal(str(avg_days))) * CYCLE_TIME_WEIGHT

    logging_ratio = partner_receipt_logged_ratio(db, partner["id"], season["id"])
    rl = Decimal(0) if logging_ratio is None else min(Decimal(str(logging_ratio)), Decimal(1))
    receipt_logging_score = rl * Decimal(RECEIPT_LOGGING_WEIGHT)

    exceptions = audit.get("transaction_test_exceptions") or 0
    exception_penalty = Decimal(EXCEPTION_PENALTY) * Decimal(exceptions)

    total = clearance_score + receipt_logging_score - exception_penalty
    if cycle_time_score is not None:
        total += cycle_time_score
    total = clamp(total, Decimal(0), Decimal(100))
    # "truncated toward zero to an integer" — the clamped total is never negative
    scorecard_total = int(total)

    grade = grade_for_total(scorecard_total)
    if partner_completed_distribution_count(db, partner["id"], season["id"]) == 0:
        grade = one_band_lower(grade)
    return scorecard_total, grade


def impact_audit_reconciliation(db, audit, season):
    shipped_units_verified, received_units_verified = audit_verified(db, audit, season)
    rate = unit_clearance_rate(shipped_units_verified, received_units_verified)
    delta = shipped_units_verified - (season.get("claim_frozen_units_total") or 0)
    total_distributions = len(_audit_distributions(db, season["id"]))
    return {
        "shipped_units_verified": shipped_units_verified,
        "received_units_verified": received_units_verified,
        "unit_clearance_rate": rate,
        "liability_reconciliation_delta": delta,
        "total_distributions": total_distributions,
    }


def critical_distribution_count(db, season_id):
    """Distributions that count toward the transaction-test sample floor.

    The catalogue does not name the marker, so every non-voided distribution of
    the season counts as critical; the sample floor is then re-derived on that
    basis.
    """
    return len(_audit_distributions(db, season_id))