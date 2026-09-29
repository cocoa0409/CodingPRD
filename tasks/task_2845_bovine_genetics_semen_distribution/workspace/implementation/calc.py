"""Every calculation in the domain (PRD 2.8, 3.4-3.9).

Money is integer cents throughout and all rounding is ROUND_HALF_UP on
decimal.Decimal -- never float, never banker's rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

import config
import store


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places):
    """Round half up to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def rh_cents(value):
    return int(rh(value, 0))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# ----------------------------------------------------- health currency ----
def health_current(sire_id):
    """PRD 2.9: one NEGATIVE, un-lapsed test per base required type."""
    now = store.clock()
    for test_type in config.BASE_REQUIRED_TEST_TYPES:
        found = False
        for test in store.DB["health_tests"].values():
            if test["sire_id"] != sire_id or test["test_type"] != test_type:
                continue
            if test["result"] != "NEGATIVE" or test["valid_until"] is None:
                continue
            if store.dt_of(test["valid_until"]) > now:
                found = True
                break
        if not found:
            return False
    return True


def base_types_covered(sire_id):
    return health_current(sire_id)


def pick_country_tests(sire_id, requirement):
    """PRD 3.7 issuance gate.  Returns the chosen test per required type, or
    None when some required type has no satisfying row."""
    now = store.clock()
    max_age = int(requirement["max_test_age_days"]) * config.DAY_SECONDS
    chosen = {}
    for test_type in requirement["required_test_types"]:
        candidates = []
        for test in store.DB["health_tests"].values():
            if test["sire_id"] != sire_id or test["test_type"] != test_type:
                continue
            if test["result"] != "NEGATIVE" or test["valid_until"] is None:
                continue
            valid_until = store.dt_of(test["valid_until"])
            if not valid_until > now:
                continue
            age = (now - store.dt_of(test["sample_date"])).total_seconds()
            if age > max_age:
                continue
            candidates.append(test)
        if not candidates:
            return None
        candidates.sort(key=lambda t: (
            store.dt_of(t["valid_until"]).timestamp() * -1, t["created_at"], t["_seq"]))
        chosen[test_type] = candidates[0]
    return chosen


# --------------------------------------------------------- lot valuation ----
def lot_standard_unit_value(processing_cost_cents, straw_count):
    """PRD 3.5: processing cost divided by straw count, half up PER STRAW."""
    return rh_cents(D(processing_cost_cents) / D(straw_count))


def lot_market_unit_value(lot, sire):
    """PRD 3.6 market basis, rounded per straw then floored at 800 cents."""
    composite = D(sire["published_composite_index"])
    if composite < 0:
        composite = D(0)
    value = D(config.BASE_CENTS_PER_INDEX_POINT) * composite
    value = value * D(config.PRODUCT_MULTIPLIER[lot["product_line"]])
    if lot["product_line"] == "SEXED":
        value = value * (D(lot["sexing_purity_pct"]) / D(config.SEXED_PURITY_REFERENCE_PCT))
    cents = rh_cents(value)
    return max(cents, config.MARKET_FLOOR_CENTS)


def lot_on_shelf_doses(lot):
    return int(lot["doses_available"]) + int(lot["doses_reserved"]) + int(lot["doses_consigned"])


def plant_inventory():
    """PRD 3.5: pure integer sum, no rounding at aggregation time."""
    total = 0
    quarantine = 0
    released = 0
    count = 0
    for lot in store.DB["straw_lots"].values():
        if lot["distribution_status"] not in ("QUARANTINE", "RELEASED"):
            continue
        value = int(lot["unit_book_value_cents"]) * lot_on_shelf_doses(lot)
        total += value
        count += 1
        if lot["distribution_status"] == "QUARANTINE":
            quarantine += value
        else:
            released += value
    return {
        "plant_inventory_value_cents": total,
        "quarantine_value_cents": quarantine,
        "released_value_cents": released,
        "lot_count": count,
    }


# ---------------------------------------------------------------- tanks ----
def tank_derived(tank):
    """PRD 3.8 liquid-nitrogen decay curve, re-derived on every read."""
    now = store.clock()
    last = store.dt_of(tank["last_service_at"])
    elapsed = (now - last).total_seconds()
    if elapsed < 0:
        elapsed = 0
    elapsed_days = int(elapsed // config.DAY_SECONDS)
    level = D(tank["last_service_fill_pct"]) - D(config.LN2_DECAY_PCT_PER_DAY) * D(elapsed_days)
    if level < 0:
        level = D(0)
    level = rh(level, 1)
    next_due = store.plus_days(last, tank["service_interval_days"])
    if level == 0:
        status = "OUT_OF_SERVICE"
    elif level <= D(config.LN2_SERVICE_DUE_PCT) or now >= next_due:
        status = "SERVICE_DUE"
    else:
        status = "IN_SERVICE"
    return level, store.iso(next_due), status


def tank_straws_on_hand(tank_id):
    """Still-outstanding doses across the tank's IN_TRANSIT and RECEIVED rows."""
    total = 0
    for transfer in store.DB["consignment_transfers"].values():
        if transfer["tank_id"] != tank_id:
            continue
        if transfer["status"] not in ("IN_TRANSIT", "RECEIVED"):
            continue
        total += transfer_doses_on_hand(transfer)
    return total


# ------------------------------------------------------------- transfers ----
def transfer_doses_on_hand(transfer):
    return int(transfer["doses"]) - int(transfer["doses_used"]) - int(transfer["doses_returned"])


def transfer_carried_value(transfer):
    """Non-zero only while the transfer is RECEIVED (PRD 3.8)."""
    if transfer["status"] != "RECEIVED":
        return 0
    lot = store.get("straw_lots", transfer["straw_lot_id"])
    if lot is None:
        return 0
    return transfer_doses_on_hand(transfer) * int(lot["unit_book_value_cents"])


def distributor_exposure(distributor_id):
    """PRD 3.8: the three derived exposure aggregates, with exact filters."""
    consignment_value = 0
    outstanding = 0
    doses_used = 0
    for transfer in store.DB["consignment_transfers"].values():
        if transfer["distributor_id"] != distributor_id:
            continue
        if transfer["status"] == "RECEIVED":
            consignment_value += transfer_carried_value(transfer)
        elif transfer["status"] == "RECONCILED":
            outstanding += int(transfer["settlement_total_cents"] or 0)
            doses_used += int(transfer["doses_used"] or 0)
    return {
        "consignment_value_cents": consignment_value,
        "outstanding_balance_cents": outstanding,
        "cumulative_doses_used": doses_used,
    }


def settlement(transfer, tank, doses_used):
    """PRD 3.8 six pinned steps; only the rebate step rounds."""
    gross = int(doses_used) * int(transfer["unit_price_cents"])
    services = 0
    if tank is not None and transfer["tank_service_count_at_dispatch"] is not None:
        services = int(tank["service_count"]) - int(transfer["tank_service_count_at_dispatch"])
    if services < 0:
        services = 0
    service_fee = config.LN2_SERVICE_FEE_CENTS * services
    subtotal = gross + service_fee
    pct = D("0.00")
    for threshold, rate in config.REBATE_TIERS:
        if subtotal >= threshold:
            pct = D(rate)
            break
    rebate = rh_cents(D(gross) * pct)
    return {
        "gross_cents": gross,
        "service_fee_cents": service_fee,
        "rebate_cents": rebate,
        "settlement_total_cents": subtotal - rebate,
    }


# --------------------------------------------------- genomic evaluation ----
def published_composite_of(sire_id):
    """Only a parent's PUBLISHED proof feeds a parent average (PRD 3.6)."""
    if sire_id is None:
        return D("0.00")
    parent = store.get("sires", sire_id)
    if parent is None:
        return D("0.00")
    return D(parent["published_composite_index"])


def score_evaluation(values, sire):
    """PRD 3.6 six pinned scoring steps."""
    production_aggregate = (
        D(config.W_MILK) * D(values["milk_kg"])
        + D(config.W_FAT) * D(values["fat_kg"])
        + D(config.W_PROTEIN) * D(values["protein_kg"])
    )
    health_aggregate = (
        D(config.W_SCS) * (D(config.SCS_BASELINE) - D(values["somatic_cell_score"])) * D(config.SCS_SCALE)
        + D(config.W_FERTILITY) * D(values["fertility_pct"])
        + D(config.W_LONGEVITY) * D(values["longevity_months"])
    )
    shrink = D(values["reliability_pct"]) / D(100)
    if shrink < D(config.SHRINK_FLOOR):
        shrink = D(config.SHRINK_FLOOR)
    elif shrink > D(config.SHRINK_CEILING):
        shrink = D(config.SHRINK_CEILING)
    # Pinned order: sub-indices are rounded BEFORE the composite is blended.
    production_index = rh(production_aggregate * shrink, 2)
    health_index = rh(health_aggregate * shrink, 2)

    daughters = int(values["progeny_daughter_count"])
    if daughters >= config.PROGENY_BLEND_MIN:
        basis = "PROGENY_BLENDED"
        weight = D(config.PA_WEIGHT_BASE) - D(config.PA_WEIGHT_SLOPE) * D(
            min(daughters, config.PA_DAUGHTER_CAP))
        if weight < D(config.PA_WEIGHT_FLOOR):
            weight = D(config.PA_WEIGHT_FLOOR)
    else:
        basis = "GENOMIC_ONLY"
        weight = D(config.PA_WEIGHT_BASE)

    parent_average = rh(
        (published_composite_of(sire["sire_id"]) + published_composite_of(sire["dam_sire_id"])) / D(2), 2)

    composite = rh(
        (D(1) - weight) * (D(config.W_PRODUCTION_BLEND) * production_index
                           + D(config.W_HEALTH_BLEND) * health_index)
        + weight * parent_average, 2)
    return {
        "evaluation_basis": basis,
        "parent_average_index": parent_average,
        "parent_average_weight": weight,
        "production_index": production_index,
        "health_index": health_index,
        "composite_index": composite,
    }


# ------------------------------------------------------------- pedigree ----
def pedigree_depth(sire_id, dam_sire_id):
    """0 for a root, else 1 + the largest parental depth (PRD 3.1)."""
    depths = []
    for parent_id in (sire_id, dam_sire_id):
        if parent_id is None:
            continue
        parent = store.get("sires", parent_id)
        depths.append(int(parent["pedigree_depth"]) if parent else 0)
    if not depths:
        return 0
    return 1 + max(depths)


def reaches(start_id, target_id):
    """True when target_id is start_id or any of its ancestors (unbounded)."""
    seen = set()
    stack = [start_id]
    while stack:
        current = stack.pop()
        if current is None or current in seen:
            continue
        seen.add(current)
        if current == target_id:
            return True
        row = store.get("sires", current)
        if row is None:
            continue
        stack.append(row["sire_id"])
        stack.append(row["dam_sire_id"])
    return False


def would_cycle(self_id, new_sire_id, new_dam_sire_id):
    """PRD 3.1: no self-edge and no cycle in the pedigree graph."""
    for parent_id in (new_sire_id, new_dam_sire_id):
        if parent_id is None:
            continue
        if parent_id == self_id:
            return True
        if reaches(parent_id, self_id):
            return True
    return False


def ancestor_distances(start_id, max_depth):
    """Shortest generation distance to every STRICT ancestor within max_depth
    edges, following both the sire_id and dam_sire_id edges (PRD 3.9)."""
    best = {start_id: 0}
    frontier = [start_id]
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        nxt = []
        for node in frontier:
            row = store.get("sires", node)
            if row is None:
                continue
            for parent_id in (row["sire_id"], row["dam_sire_id"]):
                if parent_id is None:
                    continue
                if parent_id in best:
                    continue
                best[parent_id] = depth
                nxt.append(parent_id)
        frontier = nxt
    best.pop(start_id, None)
    return best


def inbreeding_pct(candidate_id, dam_sire_id):
    """Wright's coefficient truncated at 3 generations on each side."""
    if dam_sire_id is None:
        return D("0.00")
    candidate_side = ancestor_distances(candidate_id, config.PEDIGREE_MAX_DEPTH)
    maternal_side = ancestor_distances(dam_sire_id, config.PEDIGREE_MAX_DEPTH)
    # The dam's sire himself lies on the maternal path at distance 0.
    maternal_side[dam_sire_id] = 0
    total = D(0)
    for ancestor, n1 in candidate_side.items():
        if ancestor not in maternal_side:
            continue
        n2 = maternal_side[ancestor]
        exponent = n1 + (n2 + 1) + 1
        total += D("0.5") ** exponent
    return rh(total * D(100), 2)


def conception_rate(product_line, published_composite, post_thaw_motility_pct, inbreeding):
    """PRD 3.9: clamp first, round to four decimals only at the end."""
    composite = D(published_composite)
    if composite < 0:
        composite = D(0)
    rate = D(config.BASE_CONCEPTION_RATE[product_line])
    rate = rate * (D(1) + D(config.INDEX_BONUS_PER_POINT) * composite)
    rate = rate * (D(post_thaw_motility_pct) / D(100))
    rate = rate * (D(1) - D(config.INBREEDING_PENALTY_PER_PCT) * D(inbreeding))
    if rate < D(config.CONCEPTION_FLOOR):
        rate = D(config.CONCEPTION_FLOOR)
    elif rate > D(config.CONCEPTION_CEILING):
        rate = D(config.CONCEPTION_CEILING)
    return rh(rate, 4)


def theoretical_doses(volume_ml, concentration_m_per_ml):
    """PRD 3.4: floored to a whole number of doses."""
    total = D(volume_ml) * D(concentration_m_per_ml) / D(config.DOSE_SPERM_MILLIONS)
    return int(total.to_integral_value(rounding="ROUND_FLOOR"))
