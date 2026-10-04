"""All calculation rules (SCAFFOLD.yaml section 1.3).

Every formula here is driven by the scaffold FORMULA and its `constants:`
block. Illustrative prose exemplars in `difference:` / PRD narrative are not
used to derive behaviour; where prose and formula disagree, the formula wins.
"""

import math
from datetime import timedelta

from common import round_half_up, round_half_up_int
from db import created_key, local_datetime

# --------------------------------------------------------------- constants

SMALL_LINE_FEE_RATE = 0.03
CATALOG_DISCOUNT_FACTOR = 0.97

BASE_HANDLING_RATE = 0.10
SMALL_LINE_COUNT_THRESHOLD = 5
SMALL_LINE_COUNT_REDUCTION_CENTS = 250
ORDER_LEVEL_DISCOUNT_RATE = 0.37

ZONE_SURCHARGE_CENTS = 275
EARLY_COMMIT_MINUTES = 120

GROUND_SURCHARGE_RATE = 0.00
TWO_DAY_SURCHARGE_RATE = 0.30
OVERNIGHT_SURCHARGE_RATE = 0.60

POSITIONING_SKU_THRESHOLD = 2

SECONDS_PER_DAY = 86400
REGION_CROSS_PENALTY_SECONDS = 28800

DAMAGE_VALUE_FACTOR = 0.60
DAMAGE_RATIO_TRIGGER_CENTS = 10000

RESTOCK_CAP_UNITS = 5
RESTOCK_RATIO_START = 0.80
RESTOCK_RATIO_STEP = 0.30

UNIT_MM_PER_FOOT = 304.8
WIP_STOCK_MM = 182880.0
FINISHED_STOCK_MM = 121920.0

RESTRICTED_RESERVE_RATIO = 0.80

# Lines that participate in every pricing calculation.
ELIGIBLE_LINE_STATUSES = ("PENDING", "ALLOCATED", "PICKED")


def eligible_lines(order_id, lines_by_order, store):
    """Lines of an order whose status makes them price-eligible."""
    result = []
    for line in lines_by_order.get(order_id, []):
        if line.get("line_status") in ELIGIBLE_LINE_STATUSES:
            result.append(line)
        else:
            line["allocated_small_line_fee_cents"] = 0
            line["line_total_cents"] = line.get("line_subtotal_cents", 0)
    return result


def line_subtotal(line, store):
    item = store.catalog_items.get(line.get("item_id")) or {}
    units = line.get("allocated_units", 0)
    return units * item.get("unit_price_cents", 0)


def derived_line_subtotal(line, store):
    """The line's material subtotal as derived at allocation time.

    Same quantity as `line_subtotal`; the allocation path names it separately
    because it is the value written into `line_subtotal_cents` when the line
    becomes ALLOCATED.
    """
    return line_subtotal(line, store)


# ---------------------------------------------------------------------------
# small_line_fee_total_and_allocate  (STEP 1 .. STEP 6)
# ---------------------------------------------------------------------------

def small_line_fee_total_and_allocate(order, lines, store):
    """Order-level handling pool, largest-remainder allocated to the lines."""
    eligible = [l for l in lines if l.get("line_status") in ELIGIBLE_LINE_STATUSES]
    for line in lines:
        if line.get("line_status") not in ELIGIBLE_LINE_STATUSES:
            line["allocated_small_line_fee_cents"] = 0
            line["line_total_cents"] = line.get("line_subtotal_cents", 0)

    # STEP 1 - per-line eligibility and raw fee (rounded once, here).
    for line in eligible:
        item = store.catalog_items.get(line.get("item_id")) or {}
        bundle = item.get("curation_bundle_size", 0) or 0
        sub = line.get("line_subtotal_cents", 0)
        if line.get("quantity", 0) <= bundle:
            line["raw_fee_cents"] = round_half_up_int(sub * BASE_HANDLING_RATE)
        else:
            line["raw_fee_cents"] = 0

    # STEP 2 - order-level threshold reduction, floored at 0.
    if len(eligible) >= SMALL_LINE_COUNT_THRESHOLD:
        for line in eligible:
            reduced = line["raw_fee_cents"] - SMALL_LINE_COUNT_REDUCTION_CENTS
            line["raw_fee_cents"] = reduced if reduced > 0 else 0

    # STEP 3 - round the ORDER pool, once.
    pool = sum(line["raw_fee_cents"] for line in eligible)
    order_level_discount_cents = round_half_up_int(pool * ORDER_LEVEL_DISCOUNT_RATE)
    total_fee_cents = pool - order_level_discount_cents

    # When the count threshold is NOT reached there is no order-level pool: the
    # handling fee is simply the sum of the lines' own-precision fees (PRD 3.5's
    # "fee at its own precision" basis, SMALL_LINE_FEE_RATE). The pool only exists
    # once the count reduction has fired.
    if len(eligible) < SMALL_LINE_COUNT_THRESHOLD:
        total_fee_cents = 0
        for line in eligible:
            total_fee_cents += round_half_up_int(
                line.get("line_subtotal_cents", 0) * SMALL_LINE_FEE_RATE)

    # STEP 4 - largest-remainder allocation; no re-rounding here.
    ordered = sorted(eligible, key=lambda l: (-l.get("line_subtotal_cents", 0),
                                              created_key(l)))
    if ordered and total_fee_cents > 0:
        base_share = total_fee_cents // len(ordered)
        leftover = total_fee_cents - base_share * len(ordered)
        for index, line in enumerate(ordered):
            share = base_share + (1 if index < leftover else 0)
            line["allocated_small_line_fee_cents"] = share
    else:
        for line in ordered:
            line["allocated_small_line_fee_cents"] = 0
    for line in ordered:
        line["line_total_cents"] = (line.get("line_subtotal_cents", 0)
                                    + line["allocated_small_line_fee_cents"])

    # STEP 5 - write the order-level total.
    order["total_small_line_fee_cents"] = total_fee_cents
    for line in eligible:
        line.pop("raw_fee_cents", None)
    return total_fee_cents


# ---------------------------------------------------------------------------
# order_total_two_variant / order_total_cents_factor_first
# ---------------------------------------------------------------------------

def order_total_two_variant(order, lines, store, fee_tiered=False):
    """Return (base_cents, fee_term_cents, order_total_cents).

    The material base is shared by both variants. `total_small_line_fee_cents` is
    always the handling pool written by small_line_fee_total_and_allocate (PRD
    section 3.5 step 5); the FEE TERM of the order total is what switches: the
    own-precision sum before the cutoff, the pool once the shipment is certified.
    """
    eligible = [l for l in lines if l.get("line_status") in ELIGIBLE_LINE_STATUSES]
    subtotal = sum(l.get("line_subtotal_cents", 0) for l in eligible)
    base_cents = round_half_up_int(subtotal * CATALOG_DISCOUNT_FACTOR)

    # Step 5 of the handling calculation always writes the pool total and the
    # per-line shares, whichever variant the order total uses.
    pool_total = small_line_fee_total_and_allocate(order, lines, store)

    if fee_tiered:
        total_fee = pool_total
    else:
        total_fee = 0
        for line in eligible:
            total_fee += round_half_up_int(
                line.get("line_subtotal_cents", 0) * SMALL_LINE_FEE_RATE)

    order["order_total_cents"] = base_cents + total_fee
    return base_cents, total_fee, base_cents + total_fee


def order_total_cents_factor_first(order, lines, store):
    return order_total_two_variant(order, lines, store, fee_tiered=False)


# ---------------------------------------------------------------------------
# freight_charge_two_variant / freight_surcharge_and_total
# ---------------------------------------------------------------------------

def billable_weight_kg(order, lines, store):
    total = 0.0
    for line in lines:
        if line.get("line_status") != "PICKED":
            continue
        item = store.catalog_items.get(line.get("item_id")) or {}
        total += line.get("allocated_units", 0) * float(item.get("unit_weight_kg", 0) or 0)
    return float(round_half_up(total, 2))


def base_freight_rate_cents(weight_kg):
    if weight_kg < 25.0:
        return 450
    if weight_kg < 100.0:
        return 450 + 28 * math.ceil(round(weight_kg - 25.0, 6))
    return 450 + 28 * 75 + 19 * math.ceil(round(weight_kg - 100.0, 6))


def urgency_multiplier(order, variant="cutoff_certified"):
    if variant == "leg_estimate":
        return 1.1
    if not order.get("same_day_committed"):
        return 1.0
    if order.get("commit_minutes_before_cutoff", 0) >= EARLY_COMMIT_MINUTES:
        return 1.1
    return 1.6


def freight_charge_two_variant(shipment, order, lines, account, dc, store,
                               variant="cutoff_certified"):
    weight = billable_weight_kg(order, lines, store)
    shipment["billable_weight_kg"] = weight

    zone_surcharge = 0 if dc.get("local_zone") == account.get("delivery_zone") else ZONE_SURCHARGE_CENTS
    rate = round_half_up_int((base_freight_rate_cents(weight) + zone_surcharge)
                             * urgency_multiplier(order, variant))
    shipment["freight_rate_cents"] = rate

    surcharge_rate = {
        "GROUND": GROUND_SURCHARGE_RATE,
        "TWO_DAY": TWO_DAY_SURCHARGE_RATE,
        "OVERNIGHT": OVERNIGHT_SURCHARGE_RATE,
    }.get(shipment.get("service_level", "GROUND"), 0.0)
    surcharge = round_half_up_int(rate * surcharge_rate)
    shipment["freight_surcharge_cents"] = surcharge
    shipment["freight_charge_cents"] = rate + surcharge
    order["freight_charge_cents"] = shipment["freight_charge_cents"]
    return shipment["freight_charge_cents"]


# ---------------------------------------------------------------------------
# live_availability_at_dc
# ---------------------------------------------------------------------------

def live_availability_at_dc(item_id, dc_id, store):
    for row in store.stock_rows.values():
        if row.get("item_id") == item_id and row.get("dc_id") == dc_id:
            return row.get("available_units", 0)
    return 0


def aggregate_order_availability(item_id, store):
    total = 0
    for row in store.stock_rows.values():
        if row.get("item_id") != item_id:
            continue
        available = row.get("on_hand_units", 0) - row.get("reserved_units", 0)
        if available > 0:
            total += available
    return total


# ---------------------------------------------------------------------------
# inventory_positioning_decision
# ---------------------------------------------------------------------------

def inventory_positioning_decision(dc_id, store):
    rows = [r for r in store.stock_rows.values()
            if r.get("dc_id") == dc_id and r.get("on_hand_units", 0) >= 1]

    def sort_key(row):
        item = store.catalog_items.get(row.get("item_id")) or {}
        return (item.get("sku", ""), created_key(row))

    ordered = sorted(rows, key=sort_key)
    in_stock_count = len(ordered)
    if in_stock_count >= POSITIONING_SKU_THRESHOLD:
        return "OK"
    every_long_tail = bool(ordered) and all(
        (store.catalog_items.get(r.get("item_id")) or {}).get("long_tail") is True
        for r in ordered
    )
    if in_stock_count > 0 and every_long_tail:
        return "LONG_TAIL_DEFICIT"
    return "UNDERSTOCKED"


# ---------------------------------------------------------------------------
# dc_allocation_selector
# ---------------------------------------------------------------------------

def candidate_dcs(order, lines, account, store):
    """The dc_allocation_selector candidate set (eligibility filter only)."""
    candidates = []
    for dc in store.distribution_centers.values():
        if dc.get("region") != account.get("home_region"):
            continue
        covers_all = True
        for line in lines:
            on_hand = None
            for row in store.stock_rows.values():
                if row.get("item_id") == line.get("item_id") and row.get("dc_id") == dc.get("id"):
                    on_hand = row.get("on_hand_units", 0)
                    break
            if on_hand is None or on_hand < line.get("quantity", 0):
                covers_all = False
                break
        if covers_all:
            candidates.append(dc)
    return candidates


def estimated_total_delivery_seconds(dc, account):
    total = 0
    if dc.get("cutoff_passed"):
        total += SECONDS_PER_DAY
    if dc.get("region") != account.get("home_region"):
        total += REGION_CROSS_PENALTY_SECONDS
    total += dc.get("transit_seconds", 0) or 0
    return total


def rank_dcs(candidates, account):
    return sorted(
        candidates,
        key=lambda dc: (
            estimated_total_delivery_seconds(dc, account),
            -(dc.get("cutoff_sequence_index", 0) or 0),
            created_key(dc),
        ),
    )


def select_dc(order, lines, account, store):
    candidates = candidate_dcs(order, lines, account, store)
    if not candidates:
        return None, candidates
    ranked = rank_dcs(candidates, account)
    return ranked[0], candidates


# ---------------------------------------------------------------------------
# supplier_selector
# ---------------------------------------------------------------------------

def supplier_selector(reported_available_units, store):
    candidates = [
        s for s in store.suppliers.values()
        if s.get("long_tail_authorized") is True
        and (s.get("min_stock_commitment_units", 0) or 0) >= reported_available_units
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: (
        -(s.get("performance_rating_units", 0) or 0), created_key(s)))[0]


# ---------------------------------------------------------------------------
# damaged_value_and_suspension
# ---------------------------------------------------------------------------

def damage_value_cents(claim_units, unit_price_cents):
    return round_half_up_int(claim_units * unit_price_cents * DAMAGE_VALUE_FACTOR)


def damaged_unit_ratio_breach(line, store):
    if line.get("damaged_units", 0) <= 0:
        return False
    item = store.catalog_items.get(line.get("item_id")) or {}
    return line["damaged_units"] * (item.get("unit_price_cents", 0) or 0) >= DAMAGE_RATIO_TRIGGER_CENTS


# ---------------------------------------------------------------------------
# restock_cap_allocation
# ---------------------------------------------------------------------------

def restock_cap_allocation(return_lines, store):
    """Order by delivered line_subtotal DESC, created_at ASC; 0.80 stepping down."""
    ordered = sorted(
        return_lines,
        key=lambda rl: (-_return_line_subtotal(rl, store), created_key(rl)),
    )
    remaining_ratio = RESTOCK_RATIO_START
    for rl in ordered:
        requested = rl.get("requested_return_units", 0) or 0
        restock = int(math.floor(requested * remaining_ratio))
        if restock > RESTOCK_CAP_UNITS:
            restock = RESTOCK_CAP_UNITS
        rl["restock_units"] = restock
        rl["damaged_units"] = requested - restock
        remaining_ratio = max(0.0, remaining_ratio - RESTOCK_RATIO_STEP)
    return ordered


def _return_line_subtotal(rl, store):
    line = store.order_lines.get(rl.get("line_id")) or {}
    return line.get("line_subtotal_cents", 0)


# ---------------------------------------------------------------------------
# pipe_length_commitment_two_variant
# ---------------------------------------------------------------------------

def _walk(lines, available_feet):
    """Shared walk + first-failing-line stop rule."""
    ordered = sorted(lines, key=lambda l: (l.get("cut_list_ordinal", 0), created_key(l)))
    remaining = available_feet
    allocated = 0
    for line in ordered:
        requested = line.get("requested_feet", 0) or 0
        if remaining < requested:
            line["line_committed_feet"] = 0
            for later in ordered[ordered.index(line) + 1:]:
                later["line_committed_feet"] = 0
            break
        take = min(requested, remaining)
        allocated += take
        remaining -= take
        line["line_committed_feet"] = take
    return allocated


def pipe_length_commitment_two_variant(lines, available_stock_mm=0):
    """Return (forward_looking_feet, on_hand_only_feet)."""
    available_feet = round_half_up(available_stock_mm / UNIT_MM_PER_FOOT)
    wip_feet = round_half_up(WIP_STOCK_MM / UNIT_MM_PER_FOOT)
    finished_feet = round_half_up(FINISHED_STOCK_MM / UNIT_MM_PER_FOOT)

    snapshot = {id(l): l.get("line_committed_feet", 0) for l in lines}
    forward_allocated = _walk(lines, available_feet)
    forward_total = forward_allocated + wip_feet

    for line in lines:
        line["line_committed_feet"] = snapshot[id(line)]
    on_hand_allocated = _walk(lines, available_feet)
    on_hand_total = on_hand_allocated + finished_feet
    return int(forward_total), int(on_hand_total)


def pipe_cut_length_forward_looking(lines, available_stock_mm=0):
    return pipe_length_commitment_two_variant(lines, available_stock_mm)[0]


def pipe_cut_length_on_hand_only(lines, available_stock_mm=0):
    return pipe_length_commitment_two_variant(lines, available_stock_mm)[1]


# ---------------------------------------------------------------------------
# distribution-center posture
# ---------------------------------------------------------------------------

def restricted_threshold(inbound_capacity_units):
    return math.ceil((inbound_capacity_units or 0) * RESTRICTED_RESERVE_RATIO)


def derive_posture(dc, has_open_hold):
    if has_open_hold:
        return "LOCKDOWN"
    if (dc.get("inbound_reserved_units", 0) or 0) >= restricted_threshold(dc.get("inbound_capacity_units", 0)):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# cutoff_passed
# ---------------------------------------------------------------------------

def compute_cutoff_passed(local_dt, local_cutoff_time):
    """True once the local weekday is a business day and the local wall clock
    is at or after the DC's local cutoff time."""
    if local_dt.weekday() >= 5:          # Saturday / Sunday
        return False
    try:
        hh, mm, ss = (int(part) for part in str(local_cutoff_time).split(":"))
    except (ValueError, TypeError):
        return False
    cutoff = local_dt.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    return local_dt >= cutoff


def recommend_utc_offset(store, closing_rank):
    """Pick a utc_offset_minutes placing the closing-eligibility candidate DC
    ahead of its cutoff while at least one other DC is still behind it."""
    base = store.current_utc
    dc_list = sorted(store.distribution_centers.values(), key=created_key)
    if not dc_list:
        return 0
    chosen = dc_list[closing_rank % len(dc_list)]
    hours = 10 - chosen.get("utc_offset_minutes", 0) // 60
    return ((hours + 24) % 24 or 24) * 60