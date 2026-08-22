"""Domain calculations and cascades (PRD sections 3.1-3.9).

Every evaluation order, rounding order and tie-break in this module is pinned by
PRD prose; see the referenced section on each function.
"""
from decimal import Decimal

from common import (ApiError, ceil_int, clock, dec, floor_int, round_half_up,
                    rhu_int, store, touch)

# --- constants -------------------------------------------------------------
BAND_MAX_DRAFT_FEET = {"HIGH_WATER": 12.0, "NORMAL": 12.0, "LOW": 10.5, "CRITICAL": 9.0}
BAND_TOW_SIZE_CAP = {"HIGH_WATER": 20, "NORMAL": 40, "LOW": 30, "CRITICAL": 6}
INCHES_PER_FOOT = 12

COMMODITY_GROUPS = ["GRAIN", "COAL", "CHEMICAL", "PETROLEUM", "FERTILIZER", "AGGREGATE"]
RESIDUE_CLASSES = ["CLEAN", "DUSTY", "OILY", "TOXIC"]
CLEANING_LEVELS = ["NONE", "SWEEP", "WASH", "STEAM_CERT"]
CLEANLINESS_STATUSES = ["DIRTY", "SWEPT", "WASHED", "STEAM_CERTIFIED"]

DEFAULT_REQUIRED_LEVEL = "WASH"
CLEANLINESS_RANK = {"DIRTY": 0, "SWEPT": 1, "WASHED": 2, "STEAM_CERTIFIED": 3}
REQUIRED_LEVEL_RANK = {"NONE": 0, "SWEEP": 1, "WASH": 2, "STEAM_CERT": 3}
CLEANLINESS_LEVEL_TO_STATUS = {"NONE": "DIRTY", "SWEEP": "SWEPT", "WASH": "WASHED",
                               "STEAM_CERT": "STEAM_CERTIFIED"}
CLEANING_FEE_CENTS = {"NONE": 0, "SWEEP": 45000, "WASH": 180000, "STEAM_CERT": 420000}

MIN_CUT_COUNT = 1
TOW_DELAY_STATUS_MINUTES = 120
CONTRACT_DELAY_PROTECTION_MINUTES = 150
CONTRACT_DELAY_PROTECTION_LAYTIME_HOURS = 12
LOCK_CLOSURE_DELAY_MINUTES = 240

SECONDS_PER_DAY = 86400
MIN_BILLABLE_DAYS = 1
SECONDS_PER_HOUR = 3600
NOTICE_GRACE_HOURS = 6

TRADE_TOLERANCE_PCT = Decimal("0.005")
CLAIM_FILING_WINDOW_DAYS = 30
MAX_CLAIM_REVISION_ROUNDS = 2

REBATE_TIERS = [(0, Decimal("0.0")), (1000000, Decimal("0.015")),
                (5000000, Decimal("0.03"))]

ACTIVE_ASSIGNMENT_STATUSES = ("PLANNED", "CONFIRMED", "LOADED")
BILLABLE_DISCHARGE_STATUSES = ("COMPLETED", "DISPUTED")


# ---------------------------------------------------------------------------
# 3.2  River stage band resolution and the controlling-reading selector
# ---------------------------------------------------------------------------
def dec_gt(a, b):
    """Strict greater-than evaluated on exact decimals, never on binary floats."""
    return dec(a) > dec(b)


def resolve_band(stage_feet):
    """Lower-edge-inclusive bands; stages compared at one decimal place."""
    s = round_half_up(stage_feet, 1)
    if s >= dec("25.0"):
        return "HIGH_WATER"
    if s >= dec("15.0"):
        return "NORMAL"
    if s >= dec("8.0"):
        return "LOW"
    return "CRITICAL"


def controlling_reading(gauge_station):
    now = clock.now()
    candidates = [r for r in store.river_stage_readings.values()
                  if r["gauge_station"] == gauge_station and r["reading_at"] <= now]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["reading_at"], r["created_at"], r["_seq"]),
                    reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# 3.1  Prior-cargo compatibility matrix
# ---------------------------------------------------------------------------
def find_rule(prior_group, next_group):
    for r in store.compatibility_rules.values():
        if (r["prior_commodity_group"] == prior_group
                and r["next_commodity_group"] == next_group):
            return r
    return None


def resolve_requirement(barge, next_commodity):
    """Returns (required_cleaning_level, prohibited)."""
    prior_id = barge.get("last_cargo_commodity_id")
    if not prior_id:
        return "NONE", False
    prior = store.commodities.get(prior_id)
    if prior is None:
        return "NONE", False
    next_group = next_commodity["commodity_group"] if next_commodity else None
    rule = find_rule(prior["commodity_group"], next_group)
    if rule is None:
        return DEFAULT_REQUIRED_LEVEL, False
    return rule["required_cleaning_level"], bool(rule.get("prohibited"))


def cleanliness_ok(barge, required_level):
    return (CLEANLINESS_RANK.get(barge["cleanliness_status"], 0)
            >= REQUIRED_LEVEL_RANK.get(required_level, 0))


# ---------------------------------------------------------------------------
# 3.5  Barge draft and the tow draft profile
# ---------------------------------------------------------------------------
def barge_draft(barge, loaded_tons):
    value = (dec(barge["light_draft_feet"])
             + dec(loaded_tons) / (dec(barge["tons_per_inch_immersion"]) * INCHES_PER_FOOT))
    return float(round_half_up(value, 2))


def tow_assignments(tow_id):
    return [a for a in store.barge_assignments.values() if a["tow_id"] == tow_id]


def active_assignments(tow_id):
    rows = [a for a in tow_assignments(tow_id)
            if a["status"] in ACTIVE_ASSIGNMENT_STATUSES]
    rows.sort(key=lambda a: a["cut_position"])
    return rows


def recompute_tow_profile(tow):
    """Steps 1-3 of barge_draft_and_tow_profile.  Per-barge rounding happens
    before the maximum is taken."""
    active = active_assignments(tow["id"])
    tow["barge_count"] = len(active)
    tow["total_loaded_tons"] = sum(a["loaded_tons"] for a in active)
    tow["max_draft_feet"] = max((a["barge_draft_feet"] for a in active), default=0)
    reading = controlling_reading(tow["controlling_gauge_station"])
    if reading is not None:
        tow["draft_restriction_band"] = reading["draft_restriction_band"]
        tow["allowed_draft_feet"] = reading["max_draft_feet"]
    return reading


def allowed_tons_for(tow, barge):
    value = ((dec(tow["allowed_draft_feet"]) - dec(barge["light_draft_feet"]))
             * INCHES_PER_FOOT * dec(barge["tons_per_inch_immersion"]))
    return floor_int(value)


def drop_assignment(assignment):
    """PLANNED/CONFIRMED -> DROPPED with the tow rollup and hull release."""
    assignment["status"] = "DROPPED"
    touch(assignment)
    tow = store.tows.get(assignment["tow_id"])
    if tow is not None:
        recompute_tow_profile(tow)
        touch(tow)
    barge = store.barges.get(assignment["barge_id"])
    if barge is not None and barge["operational_status"] == "IN_TOW":
        barge["operational_status"] = "IDLE"
        touch(barge)


# ---------------------------------------------------------------------------
# 3.6  Lock transit window, conflict detection and the delay cascade
# ---------------------------------------------------------------------------
def cut_count_for(tow, lock):
    raw = dec(tow["barge_count"]) / dec(lock["chamber_capacity_barges"])
    return max(MIN_CUT_COUNT, ceil_int(raw))


def window_for(tow, lock, start_at):
    from datetime import timedelta
    cuts = cut_count_for(tow, lock)
    end = start_at + timedelta(minutes=cuts * lock["cycle_minutes"])
    occupied = end + timedelta(minutes=lock["turnback_buffer_minutes"])
    return cuts, start_at, end, occupied


def window_conflicts(lock_id, start_at, occupied_until_at, exclude_id=None):
    """Half-open [scheduled_start_at, occupied_until_at); touching endpoints do
    not conflict.  Only GRANTED / IN_CHAMBER reservations block."""
    for r in store.lock_reservations.values():
        if r["lock_id"] != lock_id or r["id"] == exclude_id:
            continue
        if r["status"] not in ("GRANTED", "IN_CHAMBER"):
            continue
        if start_at < r["occupied_until_at"] and r["scheduled_start_at"] < occupied_until_at:
            return True
    return False


def attribute_delay(tow, minutes):
    """lock_delay_attribution.  Hop one always runs; hops two through four run
    only when the tow is UNDERWAY and the accrued total reaches the threshold."""
    tow["accrued_delay_minutes"] = tow.get("accrued_delay_minutes", 0) + minutes
    touch(tow)
    if tow["status"] != "UNDERWAY":
        return
    if tow["accrued_delay_minutes"] < TOW_DELAY_STATUS_MINUTES:
        return
    tow["status"] = "DELAYED"
    loaded = [a for a in tow_assignments(tow["id"]) if a["status"] == "LOADED"]
    loaded.sort(key=lambda a: a["cut_position"])
    contract_ids = []
    for a in loaded:
        a["delay_attributed_minutes"] = a.get("delay_attributed_minutes", 0) + minutes
        touch(a)
        if a["freight_contract_id"] not in contract_ids:
            contract_ids.append(a["freight_contract_id"])
    contracts = [store.freight_contracts[c] for c in contract_ids
                 if c in store.freight_contracts]
    contracts.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in contracts:
        c["accrued_delay_minutes"] = c.get("accrued_delay_minutes", 0) + minutes
        if (c["accrued_delay_minutes"] >= CONTRACT_DELAY_PROTECTION_MINUTES
                and not c.get("delay_protection_applied")):
            c["laytime_hours"] = c["laytime_hours"] + CONTRACT_DELAY_PROTECTION_LAYTIME_HOURS
            c["delay_protection_applied"] = True
        touch(c)


# ---------------------------------------------------------------------------
# 3.4  Fleeting fees and the berth aggregate head-count admission test
# ---------------------------------------------------------------------------
def days_between(start_at, end_at):
    raw = dec((end_at - start_at).total_seconds()) / SECONDS_PER_DAY
    return max(MIN_BILLABLE_DAYS, ceil_int(raw))


def estimated_fee(berth, start_at, end_at):
    return (days_between(start_at, end_at) * berth["daily_fee_cents_per_barge"]
            + berth["switch_fee_cents"])


def release_fee(berth, start_at, released_at):
    days = days_between(start_at, released_at)
    return days, days * berth["daily_fee_cents_per_barge"] + berth["switch_fee_cents"]


def berth_capacity_ok(berth, start_at, end_at):
    reserved = [f for f in store.fleeting_assignments.values()
                if f["fleeting_berth_id"] == berth["id"] and f["status"] == "RESERVED"]
    instants = {start_at}
    for f in reserved:
        if start_at <= f["start_at"] < end_at:
            instants.add(f["start_at"])
    peak = 0
    for t in instants:
        occupancy = 1 + sum(1 for f in reserved if f["start_at"] <= t < f["end_at"])
        peak = max(peak, occupancy)
    return peak <= berth["capacity_barges"]


# ---------------------------------------------------------------------------
# 3.7  Laytime clocks
# ---------------------------------------------------------------------------
def hours_up(later, earlier):
    return ceil_int(dec((later - earlier).total_seconds()) / SECONDS_PER_HOUR)


# ---------------------------------------------------------------------------
# 3.8  The charge breakdown
# ---------------------------------------------------------------------------
def contract_assignments(contract_id):
    rows = [a for a in store.barge_assignments.values()
            if a["freight_contract_id"] == contract_id]
    rows.sort(key=lambda a: a["cut_position"])
    return rows


def _pinned_filing(contract):
    fid = contract.get("pinned_tariff_filing_id")
    return store.tariff_filings.get(fid) if fid else None


def linehaul_lines(contract, variant):
    rows = contract_assignments(contract["id"])
    if variant == "FINAL":
        return [a for a in rows if a["discharge_status"] in BILLABLE_DISCHARGE_STATUSES]
    return [a for a in rows if a["status"] in ("CONFIRMED", "LOADED", "DISCHARGED")]


def tons_of(assignment, variant):
    if variant == "FINAL":
        return assignment.get("discharged_tons") or 0
    return assignment.get("loaded_tons") or 0


def compute_breakdown(contract, variant):
    filing = _pinned_filing(contract)
    rate = dec(filing["base_rate_cents_per_ton_mile"]) if filing else dec(0)
    min_charge = filing["min_charge_cents"] if filing else 0
    demurrage_rate = filing["demurrage_rate_cents_per_hour"] if filing else 0

    distance = abs(dec(contract["destination_mile"]) - dec(contract["origin_mile"]))

    lines = linehaul_lines(contract, variant)
    # Rounding order is pinned: round every line to whole cents FIRST, then sum.
    line_total = 0
    for a in lines:
        line_total += rhu_int(dec(tons_of(a, variant)) * distance * rate)
    linehaul_cents = 0 if not lines else max(line_total, min_charge)

    pct = dec(contract.get("pinned_fuel_surcharge_pct") or 0)
    fuel_surcharge_cents = rhu_int(dec(linehaul_cents) * pct)

    # Fleeting
    fleets = [f for f in store.fleeting_assignments.values()
              if f.get("freight_contract_id") == contract["id"]]
    fleets.sort(key=lambda f: (f["created_at"], f["_seq"]))
    fleeting_fee_cents = 0
    for f in fleets:
        if variant == "FINAL":
            if f["status"] == "RELEASED":
                fleeting_fee_cents += f["fee_cents"]
        else:
            if f["status"] == "RESERVED":
                fleeting_fee_cents += f["estimated_fee_cents"]
            elif f["status"] == "RELEASED":
                fleeting_fee_cents += f["fee_cents"]

    # Cleaning
    cleaning_fee_cents = 0
    for c in store.cleaning_orders.values():
        if c.get("freight_contract_id") == contract["id"] and c["status"] == "COMPLETED":
            cleaning_fee_cents += c["fee_cents"]

    # Demurrage - both variants read the discharged set only
    dem_lines = [a for a in contract_assignments(contract["id"])
                 if a["discharge_status"] in BILLABLE_DISCHARGE_STATUSES]
    laytime = contract["laytime_hours"]
    if variant == "FINAL":
        used = sum((a.get("net_laytime_hours") or 0) + NOTICE_GRACE_HOURS
                   for a in dem_lines)
        pooled = laytime * len(dem_lines)
        demurrage_cents = max(0, used - pooled) * demurrage_rate
    else:
        chargeable = sum(max(0, (a.get("gross_laytime_hours") or 0) - laytime)
                         for a in dem_lines)
        demurrage_cents = chargeable * demurrage_rate

    subtotal_cents = (linehaul_cents + fuel_surcharge_cents + fleeting_fee_cents
                      + cleaning_fee_cents + demurrage_cents)
    rebate_pct = rebate_tier(subtotal_cents)
    volume_rebate_cents = rhu_int(dec(subtotal_cents) * rebate_pct)
    claim_credit_cents = contract.get("claim_credit_cents", 0)
    total_cents = max(0, subtotal_cents - volume_rebate_cents - claim_credit_cents)

    return {
        "variant": variant,
        "billable_line_count": len(lines),
        "linehaul_cents": linehaul_cents,
        "fuel_surcharge_cents": fuel_surcharge_cents,
        "fleeting_fee_cents": fleeting_fee_cents,
        "cleaning_fee_cents": cleaning_fee_cents,
        "demurrage_cents": demurrage_cents,
        "subtotal_cents": subtotal_cents,
        "volume_rebate_cents": volume_rebate_cents,
        "claim_credit_cents": claim_credit_cents,
        "total_cents": total_cents,
    }


def rebate_tier(subtotal_cents):
    pct = REBATE_TIERS[0][1]
    for floor_cents, tier_pct in REBATE_TIERS:
        if subtotal_cents >= floor_cents:
            pct = tier_pct
    return pct


# ---------------------------------------------------------------------------
# 3.3  Tariff / fuel selectors and the credit projection
# ---------------------------------------------------------------------------
def effective_filing_for(commodity_group):
    now = clock.now()
    rows = [f for f in store.tariff_filings.values()
            if f["status"] == "EFFECTIVE" and f["commodity_group"] == commodity_group
            and f["effective_from"] <= now <= f["effective_to"]]
    if not rows:
        return None
    rows.sort(key=lambda f: (f["effective_from"], f["created_at"], f["_seq"]),
              reverse=True)
    return rows[0]


def controlling_posting():
    today = clock.now().date()
    rows = [p for p in store.fuel_index_postings.values()
            if p["_posting_date"] <= today]
    if not rows:
        return None
    rows.sort(key=lambda p: (p["_posting_date"], p["created_at"], p["_seq"]),
              reverse=True)
    return rows[0]


def surcharge_pct_for(filing, price):
    applicable = [t for t in filing["fuel_surcharge_table"]
                  if dec(t["threshold_cents_per_gallon"]) <= dec(price)]
    if not applicable:
        return 0.0
    best = max(applicable, key=lambda t: dec(t["threshold_cents_per_gallon"]))
    return best["pct"]


def projected_charge(contract, filing):
    distance = abs(dec(contract["destination_mile"]) - dec(contract["origin_mile"]))
    return rhu_int(dec(contract["contracted_tons"]) * distance
                   * dec(filing["base_rate_cents_per_ton_mile"]))


# ---------------------------------------------------------------------------
# 3.9  Claim settlement variants
# ---------------------------------------------------------------------------
def assess_claim(claim, contract, assignment):
    unit_value = dec(contract["declared_value_cents_per_ton"])
    if claim["claim_type"] == "SHORTAGE":
        shortage = dec(assignment.get("loaded_tons") or 0) - dec(
            assignment.get("discharged_tons") or 0)
    else:
        shortage = dec(claim["claimed_tons"])
    tolerance = round_half_up(dec(assignment.get("loaded_tons") or 0) * TRADE_TOLERANCE_PCT, 3)

    deductible_tons = shortage - tolerance
    if deductible_tons < 0:
        deductible_tons = dec(0)
    deductible = min(claim["claimed_amount_cents"], rhu_int(deductible_tons * unit_value))

    franchise_tons = shortage if shortage > tolerance else dec(0)
    franchise = min(claim["claimed_amount_cents"], rhu_int(franchise_tons * unit_value))

    claim["shortage_tons"] = float(shortage)
    claim["tolerance_tons"] = float(tolerance)
    claim["settlement_deductible_cents"] = deductible
    claim["settlement_franchise_cents"] = franchise


# ---------------------------------------------------------------------------
# Shipper ledger helpers (3.8, 3.9)
# ---------------------------------------------------------------------------
def credit_shipper(shipper, amount):
    shipper["outstanding_balance_cents"] = shipper["outstanding_balance_cents"] + amount
    if (shipper["outstanding_balance_cents"] > shipper["credit_limit_cents"]
            and shipper["status"] == "ACTIVE"):
        shipper["status"] = "CREDIT_HOLD"
    touch(shipper)


def relieve_shipper(shipper, amount):
    shipper["outstanding_balance_cents"] = shipper["outstanding_balance_cents"] - amount
    if (shipper["outstanding_balance_cents"] <= shipper["credit_limit_cents"]
            and shipper["status"] == "CREDIT_HOLD"):
        shipper["status"] = "ACTIVE"
    touch(shipper)
