# Calculation rules (scaffold Table 3; PRD 2.6, 2.7, 2.8, 3.4, 3.5, 3.6, 3.8).
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import constants
import state


# ---------------------------------------------------------------- bom_expansion
def bom_expand(modules):
    """Merge parts across module entries by part_number; sort ascending.
    Exact integer arithmetic, no rounding (PRD 3.4).
    Divergent part pricing (PRD 2.7: e.g. PN-WRK-SRF at 15800/17400/21500 by
    module type): the merged line's extended amount is the sum of each
    module-context contribution (qty_contribution x that module's unit price),
    which keeps parts_total_cents consistent with the pinned per-module-unit
    totals (85837/104737/180737/66300/125000) and with order_pricing step 1.
    Returns (lines, parts_total_cents, total_units)."""
    qty_by_part = {}
    ext_by_part = {}
    prices_by_part = {}
    total_units = 0
    for entry in modules:
        rule = constants.MODULE_BOM_RULES.get(entry.get("module_type"), [])
        qty = entry.get("qty", 0)
        total_units += qty
        for part_number, qty_per_unit, unit_price in rule:
            qty_by_part[part_number] = qty_by_part.get(part_number, 0) + qty_per_unit * qty
            ext_by_part[part_number] = (ext_by_part.get(part_number, 0)
                                        + qty_per_unit * qty * unit_price)
            prices_by_part.setdefault(part_number, set()).add(unit_price)
    lines = []
    parts_total = 0
    for part_number in sorted(qty_by_part.keys()):
        extended = ext_by_part[part_number]
        parts_total += extended
        prices = prices_by_part[part_number]
        lines.append({
            "part_number": part_number,
            "qty": qty_by_part[part_number],
            # A single unit price exists only when every contributing module
            # agrees; divergent parts report null rather than a lying number.
            "unit_list_price_cents": next(iter(prices)) if len(prices) == 1 else None,
            "extended_cents": extended,
        })
    return lines, parts_total, total_units


def unit_parts_cents(module_type):
    return sum(q * p for _pn, q, p in constants.MODULE_BOM_RULES[module_type])


# ------------------------------------------------------- configuration_lead_time
def fabric_delta(grade):
    if grade is None:  # STORAGE modules carry no fabric: delta 0 (PRD 2.7)
        return 0
    return constants.FABRIC_LEAD_DELTA_DAYS[grade]


def queue_days(total_units):
    if total_units <= constants.QUEUE_DAYS_SMALL_MAX_UNITS:
        return constants.QUEUE_DAYS_SMALL
    if total_units <= constants.QUEUE_DAYS_MEDIUM_MAX_UNITS:
        return constants.QUEUE_DAYS_MEDIUM
    return constants.QUEUE_DAYS_LARGE


def family_for_category(category):
    for fam in state.families.values():
        if fam["category"] == category:
            return fam
    return None


def config_lead_time(modules):
    """max over modules of (family base days + fabric delta) + queue days (PRD 3.4)."""
    best = 0
    total_units = sum(m["qty"] for m in modules)
    for entry in modules:
        category = constants.MODULE_FAMILY_CATEGORY[entry["module_type"]]
        fam = family_for_category(category)
        base = fam["base_lead_time_days"] if fam else 0
        best = max(best, base + fabric_delta(entry.get("fabric_grade")))
    return best + queue_days(total_units)


# ----------------------------------------------------------------- order_pricing
def tier_for_basis(basis_cents):
    if basis_cents >= constants.TIER3_MIN_CENTS:
        return 3
    if basis_cents >= constants.TIER2_MIN_CENTS:
        return 2
    return 1


def _round_half_up_cents(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_order(modules, agreement, tier_basis_cents):
    """Pinned 8-step evaluation (PRD 3.5). tier_basis_cents already encodes the
    PROVISIONAL-vs-FINAL difference at step 5. Returns
    (pre_discount_total_cents, tier, total_cents)."""
    pre_discount = 0
    for entry in modules:
        unit_exact = Decimal(unit_parts_cents(entry["module_type"])) * (
            Decimal(100 + constants.FABRIC_UPCHARGE_PCT.get(entry.get("fabric_grade") or "A", 0))
            / Decimal(100))
        line_total = _round_half_up_cents(unit_exact * entry["qty"])
        pre_discount += line_total
    tier = tier_for_basis(tier_basis_cents)
    discount = Decimal(str(agreement[f"tier{tier}_discount_pct"]))
    total = _round_half_up_cents(Decimal(pre_discount) * (Decimal(1) - discount))
    return pre_discount, tier, total


# ------------------------------------------------------ agreement volume ledger
def agreement_cumulative_cents(agreement_id):
    """Sum of pre_discount_total_cents over orders ACKNOWLEDGED or CLOSED
    (acknowledged and not cancelled) (PRD 3.2)."""
    total = 0
    for order in state.orders.values():
        if (order["volume_agreement_id"] == agreement_id
                and order["status"] in ("ACKNOWLEDGED", "CLOSED")
                and order["pre_discount_total_cents"] is not None):
            total += order["pre_discount_total_cents"]
    return total


def agreement_current_tier(agreement_id):
    return tier_for_basis(agreement_cumulative_cents(agreement_id))


def maybe_expire_agreement(agreement):
    """Lazy ACTIVE -> EXPIRED on any read or write (PRD 3.2). Terminal; the
    transition has no side effects (no version bump) per the state machine table."""
    if (agreement["status"] == "ACTIVE"
            and clock.today() > _parse_date(agreement["effective_end"])):
        agreement["status"] = "EXPIRED"


def _parse_date(value):
    y, m, d = value.split("-")
    from datetime import date
    return date(int(y), int(m), int(d))


def agreement_in_window(agreement):
    today = clock.today()
    return (_parse_date(agreement["effective_start"]) <= today
            <= _parse_date(agreement["effective_end"]))


# --------------------------------------------------------- plant_capacity_available
def plant_reserved_units(plant_code, production_date_iso):
    """Phases with logistics SCHEDULED or DELIVERED hold a reservation (PRD 3.6)."""
    total = 0
    for phase in state.phases.values():
        if (phase["plant_code"] == plant_code
                and phase["production_date"] == production_date_iso
                and phase["logistics_status"] in ("SCHEDULED", "DELIVERED")):
            total += phase["planned_units"]
    return total


def plant_capacity_available(plant_code, production_date_iso):
    return (constants.PLANT_DAILY_CAPACITY[plant_code]
            - plant_reserved_units(plant_code, production_date_iso))


# ------------------------------------------------------------ punch_escalation_age
def business_age_days(created_date, clock_date):
    """Count of dates d with created_date < d <= clock_date, Mon-Fri only (PRD 3.8)."""
    if clock_date <= created_date:
        return 0
    days = 0
    d = created_date + timedelta(days=1)
    while d <= clock_date:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days


def punch_escalated(ticket):
    if ticket["status"] != "OPEN":
        return False
    created_date = clock._parse_iso_datetime(ticket["created_at"]).date()
    return (business_age_days(created_date, clock.today())
            >= constants.ESCALATION_BUSINESS_DAYS)


# --------------------------------------------------------------- window logistics
def raw_overlap(a_start, a_end, b_start, b_end):
    """Strict-inequality interval overlap (PRD 2.6, 3.7)."""
    return a_start < b_end and b_start < a_end


def dates_touched(start_dt, end_dt):
    """Calendar dates the half-open interval [start, end) touches."""
    out = []
    d = start_dt.date()
    last = (end_dt - timedelta(microseconds=1)).date()
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def elevator_conflict(zone, start_dt, end_dt):
    """Freight-elevator exclusivity with 15-minute turnover buffers, per zone,
    only among RESERVED elevator_required windows (PRD 3.7)."""
    buf = timedelta(minutes=constants.FREIGHT_TURN_BUFFER_MIN)
    buffered_start = start_dt - buf
    buffered_end = end_dt + buf
    for w in state.windows.values():
        if (w["status"] != "RESERVED" or not w["elevator_required"]
                or w["building_zone_id"] != zone):
            continue
        w_start = clock._parse_iso_datetime(w["start_at"])
        w_end = clock._parse_iso_datetime(w["end_at"])
        if buffered_start < w_end and w_start < buffered_end:
            return True
    return False


def crew_capacity_exceeded(zone, start_dt, end_dt, new_crew):
    """Zone crew aggregate per calendar date over raw-overlapping RESERVED windows
    (any elevator flag); reject iff total > ZONE_MAX_CREW (PRD 3.7)."""
    for day in dates_touched(start_dt, end_dt):
        total = new_crew
        for w in state.windows.values():
            if w["status"] != "RESERVED" or w["building_zone_id"] != zone:
                continue
            w_start = clock._parse_iso_datetime(w["start_at"])
            w_end = clock._parse_iso_datetime(w["end_at"])
            if not raw_overlap(start_dt, end_dt, w_start, w_end):
                continue
            if day not in dates_touched(w_start, w_end):
                continue
            total += w["crew_size"]
        if total > constants.ZONE_MAX_CREW:
            return True
    return False
