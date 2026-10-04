"""The calculation rules of SCAFFOLD §1.3 / PRD §3.

Money is integer cents throughout; the only rounding is round-half-up at the
exact sites the rules name (PRD §2.6).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import day, parse_iso
from registry import get

MARKUP_RATE = Decimal("0.15")
PHARMACY_FEE_CENTS = 800
SHIPPING_FEE_CENTS = 500
FREE_SHIPPING_THRESHOLD_CENTS = 1500

BASE_BY_TIER = {"A": 7, "B": 14, "C": 21}
EXPANSION_GATE_MIN_SCORE = 2
SLOT_CAPACITY = 2
QUARANTINE_BUFFER_DAYS = 1
WINDOW_DAYS = 30
STALE_DEADLINE_DAYS = 30
DEMAND_HALF_OPEN_FROM = "2026-09-10T00:00:00Z"


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def manufacturer_is_active(manufacturer_id):
    manufacturer = get("manufacturers", manufacturer_id)
    return manufacturer is not None and manufacturer.get("status") == "ACTIVE"


def price_rows(drug_id):
    return [row for row in _all_prices() if row.get("drug_id") == drug_id]


def _all_prices():
    from store import store

    return list(store.prices.values())


def eligible_pool(drug_id):
    """PRD §2.10: price dimension ACTIVE, sourcing dimension SOURCED,
    offering manufacturer ACTIVE."""
    return [
        row
        for row in price_rows(drug_id)
        if row.get("price_status") == "ACTIVE"
        and row.get("sourcing_status") == "SOURCED"
        and manufacturer_is_active(row.get("manufacturer_id"))
    ]


def price_pool(drug_id):
    """Pool used by sourcing_status: ACTIVE price dimension, ACTIVE manufacturer."""
    return [
        row
        for row in price_rows(drug_id)
        if row.get("price_status") == "ACTIVE"
        and manufacturer_is_active(row.get("manufacturer_id"))
    ]


def supply_pool(drug_id):
    """supply_units sums units of rows at SOURCED or UNDER_REVIEW (PRD §3.2)."""
    return [
        row
        for row in price_rows(drug_id)
        if row.get("sourcing_status") in ("SOURCED", "UNDER_REVIEW")
        and manufacturer_is_active(row.get("manufacturer_id"))
    ]


def effective_unit_cost_cents(pool):
    """Available-units-weighted average over the pool, one round-half-up."""
    if not pool:
        return None
    units = sum(int(row.get("available_units") or 0) for row in pool)
    if units == 0:
        return None
    weighted = sum(
        int(row.get("unit_cost_cents") or 0) * int(row.get("available_units") or 0)
        for row in pool
    )
    return round_half_up(Decimal(weighted) / Decimal(units))


def lowest_unit_cost_cents(pool):
    """The single-cheapest patient-facing view; null on an empty pool."""
    if not pool:
        return None
    return min(int(row.get("unit_cost_cents") or 0) for row in pool)


def primary_row(pool):
    """The OVERVIEW primary: lowest unit cost, ties on units DESC then
    created_at ASC (SCAFFOLD §1.3 primary_source_cost)."""
    if not pool:
        return None
    return sorted(
        pool,
        key=lambda row: (
            int(row.get("unit_cost_cents") or 0),
            -int(row.get("available_units") or 0),
            row.get("created_at") or "",
            row.get("id") or "",
        ),
    )[0]


def per_row_interval(row):
    base = BASE_BY_TIER.get(row.get("reliability_tier"), 7)
    units = int(row.get("available_units") or 0)
    if units >= 200:
        adjustment = -7
    elif units >= 50:
        adjustment = 0
    else:
        adjustment = 14
    return base + adjustment


def shipment_interval_days(pool):
    """max of the per-row intervals over the pool; null on an empty pool."""
    if not pool:
        return None
    return max(per_row_interval(row) for row in pool)


def sourcing_status(drug_id):
    """PRD §3.2: UNSOURCED / UNDER_REVIEW / SOURCED over the ACTIVE-price pool."""
    pool = price_pool(drug_id)
    if not pool:
        return "UNSOURCED"
    if sum(int(row.get("available_units") or 0) for row in pool) == 0:
        return "UNDER_REVIEW"
    if any(row.get("sourcing_status") == "SOURCED" for row in pool):
        return "SOURCED"
    return "UNDER_REVIEW"


def supply_units(drug_id):
    return sum(int(row.get("available_units") or 0) for row in supply_pool(drug_id))


def drug_reserved_total(drug_id):
    """Claim-active reservations held against the drug's supply."""
    from store import store

    total = 0
    for claim in store.claims.values():
        if claim.get("status") in ("DENIED", "CANCELED"):
            continue
        prescription = get("prescriptions", claim.get("prescription_id"))
        if prescription is None or prescription.get("drug_id") != drug_id:
            continue
        total += int(claim.get("reserved_quantity") or 0)
    return total


def demand_units_30d(drug_id, clock, transitioning_request=None, transition_to=None):
    """PRD §3.4 demand window: trailing 30 days, SUBMITTED/UNDER_REVIEW/ACCEPTED,
    half-open [clock-30d, clock) from the pinned cut-over instant onward."""
    from store import store

    window_start = clock - timedelta(days=WINDOW_DAYS)
    half_open_from = parse_iso(DEMAND_HALF_OPEN_FROM)
    half_open = clock >= half_open_from
    total = 0
    for request in store.requests.values():
        status = request.get("status")
        if transitioning_request is not None and request.get("id") == transitioning_request.get("id"):
            status = transition_to
        if status not in ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED"):
            continue
        prescription = get("prescriptions", request.get("prescription_id"))
        if prescription is None or prescription.get("drug_id") != drug_id:
            continue
        created = parse_iso(request.get("submitted_at") or request.get("created_at"))
        if created is None:
            continue
        if half_open:
            # PRD §3.4: "a newly created request is inside the demand window",
            # so the clock instant itself counts; only the window's start moves
            # with the pinned cut-over.
            inside = window_start <= created <= clock
        else:
            inside = window_start < created <= clock
        if inside:
            total += int(request.get("packaged_quantity") or 0)
    return total


def has_active_manufacturer_candidate(drug_id):
    return any(
        manufacturer_is_active(row.get("manufacturer_id")) for row in price_rows(drug_id)
    )


def expansion_score(drug, demand, supply):
    """PRD §3.3 boundaries: 1 / 2 / 3 / 0, and null in three exclusions.

    The band boundaries are evaluated only over a positive demand: the gate
    already refuses a drug whose `demand_units_30d` is below 1, and the score is
    null when supply is zero with positive demand, so those cases never reach a
    numbered band.
    """
    if drug.get("is_controlled") is True:
        return None
    if not has_active_manufacturer_candidate(drug.get("id")):
        return None
    if demand < 1:
        return None
    if demand >= supply:
        return 1
    if supply < 2 * demand:
        return 2
    if supply <= 10 * demand:
        return 3
    return 0


def order_decomposition(order):
    """SCAFFOLD §1.3 order_price: blend, then provisional, then final assembly."""
    source = get("prices", order.get("source_price_id"))
    fallback = get("prices", order.get("sub_source_price_id"))
    quantity = int(order.get("quantity") or 0)
    if quantity <= 0:
        quantity = 1
    if source is None:
        source_units = 0
        source_cost = 0
    else:
        source_units = int(source.get("available_units") or 0)
        source_cost = int(source.get("unit_cost_cents") or 0)

    if fallback is None or source_units >= quantity:
        primary_units = quantity
        fallback_units = 0
        blended = source_cost * quantity
        is_blended = False
    else:
        primary_units = source_units
        fallback_units = quantity - primary_units
        blended = source_cost * primary_units + int(
            fallback.get("unit_cost_cents") or 0
        ) * fallback_units
        is_blended = True

    acquisition = round_half_up(Decimal(blended) / Decimal(quantity))
    markup = round_half_up(Decimal(acquisition) * MARKUP_RATE)
    provisional = acquisition + markup + PHARMACY_FEE_CENTS + SHIPPING_FEE_CENTS
    shipping = 0 if provisional >= FREE_SHIPPING_THRESHOLD_CENTS else SHIPPING_FEE_CENTS
    patient_price = acquisition + markup + PHARMACY_FEE_CENTS + shipping
    return {
        "acquisition_cost_cents": acquisition,
        "is_blended_cost": is_blended,
        "primary_units": primary_units,
        "fallback_units": fallback_units,
        "markup_cents": markup,
        "pharmacy_fee_cents": PHARMACY_FEE_CENTS,
        "shipping_fee_cents": shipping,
        "patient_price_cents": patient_price,
    }


def slot_occupancy(drug_id):
    """calendar day -> shipments of the drug occupying that day (PRD §3.7)."""
    from store import store

    counts = {}
    for shipment in store.shipments.values():
        if shipment.get("status") not in ("DISPATCHED", "IN_TRANSIT", "DELIVERED"):
            continue
        order = get("orders", shipment.get("order_id"))
        if order is None:
            continue
        prescription = get("prescriptions", order.get("prescription_id"))
        if prescription is None or prescription.get("drug_id") != drug_id:
            continue
        dispatched = parse_iso(shipment.get("dispatch_at"))
        if dispatched is None:
            continue
        dispatch_day = day(dispatched)
        counts[dispatch_day] = counts.get(dispatch_day, 0) + 1
        buffer_day = dispatch_day - timedelta(days=QUARANTINE_BUFFER_DAYS)
        counts[buffer_day] = counts.get(buffer_day, 0) + 1
    return counts


def slot_conflict(drug_id, clock):
    """True when the dispatch day or its buffer day already carries SLOT_CAPACITY."""
    counts = slot_occupancy(drug_id)
    dispatch_day = day(clock)
    if counts.get(dispatch_day, 0) >= SLOT_CAPACITY:
        return True
    buffer_day = dispatch_day - timedelta(days=QUARANTINE_BUFFER_DAYS)
    if counts.get(buffer_day, 0) >= SLOT_CAPACITY:
        return True
    return False