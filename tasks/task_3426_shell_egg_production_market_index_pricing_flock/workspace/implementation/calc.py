"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All fractional arithmetic uses
Fraction so flooring and half-up rounding are exact."""

from datetime import timedelta
from fractions import Fraction

from db import STORE, touch
from errors import ApiError, ERR_NO_LAYING_FLOCK_FOR_PROGRAM
from util import ceil_frac, floor_frac, round_half_up

# ---------------------------------------------------------------------------
# Named constants (SCAFFOLD calculations[].constants)
# ---------------------------------------------------------------------------
GROWING_WEEKS = 18
MOLT_DURATION_WEEKS = 4
MOLT_MIN_AGE_WEEKS = 50
AUTO_DEPLETE_AGE_WEEKS = 80
PLACEMENT_MAX_AGE_WEEKS = 30
WEEKLY_MORTALITY_BPS = 10
POST_MOLT_RATE_FACTOR = Fraction(95, 100)
CERT_VALIDITY_DAYS = 365
OCCUPANCY_DAYS = 560
CASE_DOZEN = 30
SUPPORT_HENS_PER_WEEKLY_DOZEN = 2
REGIONAL_DISEASE_BONUS_DAYS = 14
DISPOSAL_DOWNTIME_DAYS = {
    "COMPOSTING": 42,
    "BURIAL": 28,
    "INCINERATION": 21,
    "LANDFILL": 35,
}
STANDARD_BLEND_CENTS_PER_TON = 25200  # 0.60 * 18000 + 0.40 * 36000

UNGRADED_FIELD = {
    "CONVENTIONAL": "ungraded_conventional_dozen",
    "CAGE_FREE": "ungraded_cage_free_dozen",
    "ORGANIC": "ungraded_organic_dozen",
}

SIZES = ["JUMBO", "EXTRA_LARGE", "LARGE", "MEDIUM", "SMALL", "PEEWEE"]
BAND_DIST = {
    "YOUNG": {
        "JUMBO": Fraction(2, 100), "EXTRA_LARGE": Fraction(12, 100),
        "LARGE": Fraction(38, 100), "MEDIUM": Fraction(30, 100),
        "SMALL": Fraction(14, 100), "PEEWEE": Fraction(4, 100),
    },
    "PEAK": {
        "JUMBO": Fraction(8, 100), "EXTRA_LARGE": Fraction(24, 100),
        "LARGE": Fraction(42, 100), "MEDIUM": Fraction(18, 100),
        "SMALL": Fraction(6, 100), "PEEWEE": Fraction(2, 100),
    },
    "OLD": {
        "JUMBO": Fraction(12, 100), "EXTRA_LARGE": Fraction(30, 100),
        "LARGE": Fraction(36, 100), "MEDIUM": Fraction(14, 100),
        "SMALL": Fraction(6, 100), "PEEWEE": Fraction(2, 100),
    },
}

VOLUME_TIERS = {
    "RETAIL": [(500000, 2), (2000000, 4)],
    "FOODSERVICE": [(1000000, 2), (5000000, 5)],
    "PROCESSOR": [(2500000, 3), (10000000, 6)],
}

ACTIVE_FLOCK_STATUSES = ("GROWING", "LAYING", "MOLT")


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------
def house_of_flock(flock):
    return STORE.houses.get(flock["house_id"])


def complex_of_house(house):
    return STORE.complexes.get(house["complex_id"])


def complex_of_flock(flock):
    house = house_of_flock(flock)
    return complex_of_house(house) if house else None


def commitment_of_order(order):
    return STORE.commitments.get(order["commitment_id"])


def customer_of_commitment(commitment):
    return STORE.customers.get(commitment["customer_id"])


# ---------------------------------------------------------------------------
# calculations.lay_rate_curve (PRD §3.2)
# ---------------------------------------------------------------------------
def lay_rate(age_weeks, molt_count):
    if age_weeks < 18:
        base = Fraction(0)
    elif age_weeks <= 25:
        base = Fraction(85, 100)
    elif age_weeks <= 50:
        base = Fraction(92, 100)
    elif age_weeks <= 70:
        base = Fraction(85, 100)
    else:
        base = Fraction(78, 100)
    if molt_count >= 1:
        base *= POST_MOLT_RATE_FACTOR
    return base


def weekly_lay_dozen(hen_count, age_weeks, molt_count):
    """floor(current_hen_count * lay_rate * 7 / 12), floored per flock per week."""
    return floor_frac(Fraction(hen_count) * lay_rate(age_weeks, molt_count) * 7 / 12)


# ---------------------------------------------------------------------------
# calculations.biosecurity_posture (PRD §2.7) — derived, never assigned
# ---------------------------------------------------------------------------
def compute_posture(complex_id):
    cx = STORE.complexes.get(complex_id)
    if cx is None:
        return "NORMAL"
    own_confirmed = False
    own_suspected = False
    region_confirmed = False
    for e in STORE.disease_events.values():
        if e["complex_id"] == complex_id:
            if e["status"] == "CONFIRMED":
                own_confirmed = True
            elif e["status"] == "SUSPECTED":
                own_suspected = True
        elif e["status"] == "CONFIRMED":
            other = STORE.complexes.get(e["complex_id"])
            if other is not None and other["region_code"] == cx["region_code"]:
                region_confirmed = True
    if own_confirmed:
        return "QUARANTINE"
    if own_suspected or region_confirmed:
        return "ELEVATED"
    return "NORMAL"


def recompute_postures():
    """Recompute every complex's posture (region-wide is a subset of this and
    equivalent, since a complex's posture depends only on its own region)."""
    for cx in STORE.complexes.values():
        posture = compute_posture(cx["id"])
        if cx["biosecurity_posture"] != posture:
            cx["biosecurity_posture"] = posture
            touch(cx)


def recompute_hen_inventory(house, do_touch=True):
    """hen_inventory = sum of current_hen_count over the house's flocks in
    {GROWING, LAYING, MOLT}."""
    total = sum(
        f["current_hen_count"]
        for f in STORE.flocks.values()
        if f["house_id"] == house["id"] and f["status"] in ACTIVE_FLOCK_STATUSES
    )
    if house["hen_inventory"] != total:
        house["hen_inventory"] = total
        if do_touch:
            touch(house)


# ---------------------------------------------------------------------------
# calculations.laying_capacity_projection (PRD §3.6)
# ---------------------------------------------------------------------------
def capacity_projection(complex_id, week_offset):
    """Returns {'CONVENTIONAL': n, 'CAGE_FREE': n, 'ORGANIC': n}; hens frozen
    at current_hen_count (future mortality deliberately ignored)."""
    per = {"CONVENTIONAL": 0, "CAGE_FREE": 0, "ORGANIC": 0}
    for f in STORE.flocks.values():
        if f["status"] not in ACTIVE_FLOCK_STATUSES:
            continue
        house = house_of_flock(f)
        if house is None or house["complex_id"] != complex_id:
            continue
        projected_age = f["age_weeks"] + week_offset
        if projected_age >= AUTO_DEPLETE_AGE_WEEKS:
            continue
        if projected_age < GROWING_WEEKS:
            continue
        per[f["program"]] += weekly_lay_dozen(
            f["current_hen_count"], projected_age, f["molt_count"]
        )
    return per


# ---------------------------------------------------------------------------
# calculations.order_allocation_capacity (PRD §3.6)
# ---------------------------------------------------------------------------
def select_allocation(order, commitment):
    """Returns the chosen Complex, or None when the candidate pool is empty
    (empty pool -> the order becomes BLOCKED; it is not an error)."""
    clock = STORE.clock
    week_start = order["_dt_ship_week_start"]
    offset = max(0, (week_start - clock).days // 7)
    best = None  # (available, seq, complex)
    for cx in STORE.complexes.values():
        if cx["region_code"] != commitment["region_code"]:
            continue
        if cx["biosecurity_posture"] == "QUARANTINE":
            available = 0
        else:
            per = capacity_projection(cx["id"], offset)
            committed = sum(
                o["allocated_dozen"] or 0
                for o in STORE.orders.values()
                if o.get("allocated_complex_id") == cx["id"]
                and o["status"] in ("ALLOCATED", "SHIPPED")
                and o.get("_dt_ship_week_start") == week_start
            )
            available = max(0, sum(per.values()) - committed)
        if available >= order["dozen_ordered"]:
            if (
                best is None
                or available > best[0]
                or (available == best[0] and cx["_seq"] < best[1])
            ):
                best = (available, cx["_seq"], cx)
    return best[2] if best else None


# ---------------------------------------------------------------------------
# calculations.settlement_index_pricing (PRD §3.4)
# ---------------------------------------------------------------------------
def latest_quotation(region_code, size_class, clock):
    """Point observation: latest effective_date at or before the clock, ties
    broken by later quotation creation."""
    best = None
    for q in STORE.quotations.values():
        if q["region_code"] != region_code or q["size_class"] != size_class:
            continue
        if q["_dt_effective_date"] > clock:
            continue
        key = (q["_dt_effective_date"], q["_seq"])
        if best is None or key > best[0]:
            best = (key, q)
    return best[1] if best else None


def week_quotations(region_code, size_class, week_start):
    """All quotations whose effective_date falls in the half-open settlement
    week [ship_week_start, ship_week_start + 7 days)."""
    week_end = week_start + timedelta(days=7)
    qs = [
        q
        for q in STORE.quotations.values()
        if q["region_code"] == region_code
        and q["size_class"] == size_class
        and week_start <= q["_dt_effective_date"] < week_end
    ]
    qs.sort(key=lambda q: (q["_dt_effective_date"], q["_seq"]))
    return qs


def week_average(region_code, size_class, week_start):
    """round_half_up(mean of price_cents_per_dozen over the week window);
    returns (avg or None, quotation ids in window order)."""
    qs = week_quotations(region_code, size_class, week_start)
    if not qs:
        return None, []
    avg = round_half_up(
        Fraction(sum(q["price_cents_per_dozen"] for q in qs), len(qs))
    )
    return avg, [q["id"] for q in qs]


def volume_discount(segment, week_spend_cents):
    """Greatest spend threshold not exceeding the week spend wins; 0 if none."""
    best_threshold = -1
    discount = 0
    for threshold, disc in VOLUME_TIERS[segment]:
        if week_spend_cents >= threshold and threshold > best_threshold:
            best_threshold = threshold
            discount = disc
    return discount


def compute_final_pricing(settlement, order, commitment, customer):
    """Pinned six-step FINAL evaluation order (PRD §3.4). Returns
    (index_avg, discount, unit_price, total, quotation_ids_used)."""
    week_start = settlement["_dt_ship_week_start"]
    # (1) week-window average for this order's region/size
    index_avg, quotation_ids = week_average(
        commitment["region_code"], order["size_class"], week_start
    )
    # (2) pre-discount unit price
    pre_discount_unit = index_avg + commitment["price_adjustment_cents_per_dozen"]
    # (3) customer week spend over SHIPPED/SETTLED orders in the same week,
    #     using pre-discount unit prices only
    week_spend = 0
    for o2 in STORE.orders.values():
        if o2.get("_dt_ship_week_start") != week_start:
            continue
        if o2["status"] not in ("SHIPPED", "SETTLED"):
            continue
        cm2 = STORE.commitments.get(o2["commitment_id"])
        if cm2 is None or cm2["customer_id"] != customer["id"]:
            continue
        avg2, _ = week_average(cm2["region_code"], o2["size_class"], week_start)
        if avg2 is None:
            continue
        week_spend += (o2["allocated_dozen"] or 0) * (
            avg2 + cm2["price_adjustment_cents_per_dozen"]
        )
    # (4) segment-keyed volume discount
    discount = volume_discount(customer["segment"], week_spend)
    # (5)/(6) final unit price and total
    unit = pre_discount_unit - discount
    total = settlement["dozen_shipped"] * unit
    return index_avg, discount, unit, total, quotation_ids


# ---------------------------------------------------------------------------
# calculations.packing_size_distribution (PRD §3.9)
# ---------------------------------------------------------------------------
def _band_for_age(age_weeks):
    if age_weeks <= 25:
        return "YOUNG"
    if age_weeks <= 50:
        return "PEAK"
    return "OLD"


def packing_distribution(complex_id, program, dozen_input):
    """Returns (cases_by_size, total_cases). Round per size class first (floor),
    then reconcile the remainder by largest fractional part, ties broken by
    size declaration order."""
    candidates = [
        f
        for f in STORE.flocks.values()
        if f["status"] == "LAYING"
        and f["program"] == program
        and (house_of_flock(f) or {}).get("complex_id") == complex_id
    ]
    if not candidates:
        raise ApiError(
            ERR_NO_LAYING_FLOCK_FOR_PROGRAM,
            422,
            "no LAYING flock for program %s in this complex" % program,
        )
    weights = [
        (f, weekly_lay_dozen(f["current_hen_count"], f["age_weeks"], f["molt_count"]))
        for f in candidates
    ]
    total_weight = sum(w for _, w in weights)
    blended = {}
    for size in SIZES:
        if total_weight > 0:
            numerator = sum(
                Fraction(w) * BAND_DIST[_band_for_age(f["age_weeks"])][size]
                for f, w in weights
            )
            blended[size] = numerator / total_weight
        else:
            # Degenerate all-zero weights: fall back to an unweighted blend so
            # the distribution stays defined.
            blended[size] = sum(
                BAND_DIST[_band_for_age(f["age_weeks"])][size] for f, _ in weights
            ) / len(weights)
    total_cases = dozen_input // CASE_DOZEN
    floors = {}
    frac_parts = {}
    for size in SIZES:
        raw = Fraction(total_cases) * blended[size]
        fl = floor_frac(raw)
        floors[size] = fl
        frac_parts[size] = raw - fl
    remainder = total_cases - sum(floors.values())
    ranked = sorted(
        SIZES, key=lambda s: (frac_parts[s], -SIZES.index(s)), reverse=True
    )
    for size in ranked[:remainder]:
        floors[size] += 1
    return {size: floors[size] for size in SIZES}, total_cases


# ---------------------------------------------------------------------------
# calculations.feed_batch_costing (PRD §3.8)
# ---------------------------------------------------------------------------
def receipt_cost(contract, tons, spot_cents_per_ton):
    """Hedged share (earliest receipts first) prices at futures + basis; the
    remainder at the receipt's spot + basis. Returns (cost, hedged_share)."""
    hedged_share = min(tons, contract["hedged_tons"] - contract["hedged_applied_tons"])
    if hedged_share < 0:
        hedged_share = 0
    cost = 0
    if hedged_share > 0:
        cost += hedged_share * (
            contract["hedge_futures_cents_per_ton"] + contract["basis_cents_per_ton"]
        )
    unhedged = tons - hedged_share
    if unhedged > 0:
        cost += unhedged * (spot_cents_per_ton + contract["basis_cents_per_ton"])
    return cost, hedged_share


def consume_feed(complex_id, commodity, organic, tons_needed):
    """FIFO: contracts of the matching commodity and pool ordered by
    first-receipt clock ASC, tie-break contract created_at ASC. Returns
    [(contract, drawn_tons)]. Caller has already verified pool sufficiency."""
    contracts = [
        c
        for c in STORE.feed_contracts.values()
        if c["complex_id"] == complex_id
        and c["commodity"] == commodity
        and c["is_organic_certified"] == organic
        and c["received_tons"] - c.get("_consumed_tons", 0) > 0
    ]
    contracts.sort(key=lambda c: (c.get("_dt_first_receipt_at"), c["_seq"]))
    draws = []
    remaining = tons_needed
    for c in contracts:
        if remaining <= 0:
            break
        available = c["received_tons"] - c.get("_consumed_tons", 0)
        take = min(available, remaining)
        if take > 0:
            draws.append((c, take))
            remaining -= take
    return draws


def blended_cost(corn_draws, soy_draws, total_tons):
    """Ton-weighted blend of consumed contracts' average received costs,
    rounded half-up to a whole cent per ton."""
    weighted = 0
    for contract, tons in list(corn_draws) + list(soy_draws):
        weighted += tons * contract["average_received_cost_cents_per_ton"]
    return round_half_up(Fraction(weighted, total_tons))


# ---------------------------------------------------------------------------
# calculations.depopulation_downtime (PRD §3.3)
# ---------------------------------------------------------------------------
def depop_downtime_days(event, disposal_method, clock):
    days = DISPOSAL_DOWNTIME_DAYS[disposal_method]
    own_complex = STORE.complexes.get(event["complex_id"])
    for e in STORE.disease_events.values():
        if e["complex_id"] == event["complex_id"]:
            continue  # only OTHER complexes count
        if e["status"] != "CONFIRMED":
            continue
        other = STORE.complexes.get(e["complex_id"])
        if other is None or own_complex is None:
            continue
        if other["region_code"] != own_complex["region_code"]:
            continue
        confirmed_at = e.get("_dt_confirmed_at")
        if confirmed_at is not None and clock - timedelta(days=30) <= confirmed_at <= clock:
            days += REGIONAL_DISEASE_BONUS_DAYS
            break
    return days


# ---------------------------------------------------------------------------
# calculations.commitment_transition_progress (PRD §3.5)
# ---------------------------------------------------------------------------
def commitment_progress(commitment):
    pct = commitment.get("required_cage_free_pct")
    pct_frac = Fraction(str(pct)) if pct is not None else Fraction(0)
    required = round_half_up(
        Fraction(commitment["weekly_dozen_committed"])
        * pct_frac
        * SUPPORT_HENS_PER_WEEKLY_DOZEN
    )
    achieved = 0
    for p in STORE.capital_projects.values():
        if p["commitment_id"] == commitment["id"] and p["status"] == "COMMISSIONED":
            house = STORE.houses.get(p["house_id"])
            if house is not None:
                achieved += house["capacity_hens"]
    deadline = commitment.get("_dt_cage_free_transition_deadline")
    on_track = achieved >= required or (
        deadline is not None and STORE.clock < deadline
    )
    return required, achieved, on_track


def ceil_div(numerator, denominator):
    return ceil_frac(Fraction(numerator, denominator))
