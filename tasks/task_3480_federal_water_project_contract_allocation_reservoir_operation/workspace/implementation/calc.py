"""Calculation rules (SCAFFOLD section 1.3; PRD sections 3.3-3.7).

All rounding is round-half-up, applied exactly where each rule states it.
Money and energy use Decimal; floats are never used for money.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import DB, clock_now, touch

CFS_DAY_TO_AF = Decimal("1.9835")
FC_HOLDBACK_PCT = Decimal("0.10")
FLOOD_MONTHS = (11, 12, 1, 2, 3)
TIER_1_THRESHOLD_PCT = 75  # strict less-than against declared*100 / total_max*100
TIER_2_THRESHOLD_PCT = 50
TRANSFER_REVISION_CAP = 3
OBJECTION_WINDOW_HOURS = 72

QUANT_INT = Decimal("1")
QUANT_MWH = Decimal("0.01")

ACTIVE_ORDER_STATES = ("CONFIRMED", "PARTIALLY_DELIVERED")


def rhu_int(value):
    """Round-half-up a Decimal to an integer."""
    return int(value.quantize(QUANT_INT, rounding=ROUND_HALF_UP))


def rhu_2dp(value):
    """Round-half-up a Decimal to two decimal places (MWh)."""
    return value.quantize(QUANT_MWH, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def singleton_reservoir():
    for r in DB["reservoirs"].values():
        return r
    return None


def open_incident_count(reservoir_id):
    return sum(1 for i in DB["incidents"].values()
               if i["reservoir_id"] == reservoir_id and i["status"] == "OPEN")


def reservoir_posture(reservoir_id):
    return "COMPLIANCE_HOLD" if open_incident_count(reservoir_id) > 0 else "NORMAL"


def active_contracts():
    return [c for c in DB["contracts"].values() if c["status"] == "ACTIVE"]


def latest_observation(water_year_id, observation_type):
    """Latest by observed_on; ties broken by created_at DESC then arrival DESC."""
    best = None
    for o in DB["observations"].values():
        if o["water_year_id"] != water_year_id or o["observation_type"] != observation_type:
            continue
        if best is None or (o["observed_on"], o["created_at"], o["_seq"]) > (
                best["observed_on"], best["created_at"], best["_seq"]):
            best = o
    return best


def lines_of(announcement_id):
    return [l for l in DB["allocation_lines"].values()
            if l["announcement_id"] == announcement_id]


def line_for(announcement_id, contract_id):
    if announcement_id is None:
        return None
    for l in DB["allocation_lines"].values():
        if l["announcement_id"] == announcement_id and l["contract_id"] == contract_id:
            return l
    return None


def current_line(year, contract_id):
    return line_for(year["current_announcement_id"], contract_id)


def orders_on_line(line_id):
    return [o for o in DB["delivery_orders"].values()
            if o["allocation_line_id"] == line_id]


# ---------------------------------------------------------------------------
# Allocation math (PRD section 3.3)
# ---------------------------------------------------------------------------

def declared_supply(year):
    """forecast_declared_supply: storage + adjusted forecast - flood holdback."""
    f_obs = latest_observation(year["id"], "RUNOFF_FORECAST_AF")
    p_obs = latest_observation(year["id"], "SNOWPACK_INDEX")
    forecast = f_obs["value"] if f_obs else 0
    snowpack = p_obs["value"] if p_obs else 0
    forecast_adjusted = rhu_int(Decimal(forecast) * Decimal(snowpack) / Decimal(100))
    reservoir = singleton_reservoir()
    if reservoir is not None:
        usable_storage = max(0, reservoir["current_storage_af"] - reservoir["dead_pool_af"])
        if clock_now().month in FLOOD_MONTHS:
            holdback = rhu_int(Decimal(reservoir["flood_control_max_storage_af"]) * FC_HOLDBACK_PCT)
        else:
            holdback = 0
    else:
        usable_storage = 0
        holdback = 0
    return max(0, usable_storage + forecast_adjusted - holdback)


def shortage_tier(declared_supply_af):
    """Exact-arithmetic thresholds: strict < 0.50 -> TIER_2, strict < 0.75 -> TIER_1."""
    total_max = sum(c["max_annual_quantity_af"] for c in active_contracts())
    if total_max == 0:
        return "NONE"
    if declared_supply_af * 100 < TIER_2_THRESHOLD_PCT * total_max:
        return "TIER_2"
    if declared_supply_af * 100 < TIER_1_THRESHOLD_PCT * total_max:
        return "TIER_1"
    return "NONE"


def waterfall_allocations(contracts, declared_supply_af):
    """SENIOR before JUNIOR; within a class created_at ASC, tie contract_number ASC.
    Each receives min(max_annual_quantity_af, remaining); the boundary is inclusive."""
    def sort_key(c):
        return (0 if c["priority_class"] == "SENIOR" else 1,
                c["created_at"], c["contract_number"], c["_seq"])

    remaining = declared_supply_af
    allocations = {}
    for c in sorted(contracts, key=sort_key):
        award = min(c["max_annual_quantity_af"], remaining)
        allocations[c["id"]] = award
        remaining -= award
    return allocations


def sharing_allocations(contracts, declared_supply_af, tier, agreement):
    """Guarantee-percentage sharing (PRD section 3.4): per-contract round-half-up
    before the cap; JUNIOR lines reduced newest-first; SENIOR never reduced."""
    if tier == "TIER_2":
        senior_pct = agreement["tier_2_senior_pct"]
        junior_pct = agreement["tier_2_junior_pct"]
    else:
        # TIER_1 columns; also the only defined columns if the tier is NONE.
        senior_pct = agreement["tier_1_senior_pct"]
        junior_pct = agreement["tier_1_junior_pct"]
    shares = {}
    for c in contracts:
        pct = senior_pct if c["priority_class"] == "SENIOR" else junior_pct
        shares[c["id"]] = rhu_int(Decimal(c["max_annual_quantity_af"]) * Decimal(pct) / Decimal(100))
    if sum(shares.values()) > declared_supply_af:
        juniors = [c for c in contracts if c["priority_class"] == "JUNIOR"]
        juniors.sort(key=lambda c: (c["created_at"], c["contract_number"], c["_seq"]),
                     reverse=True)
        for c in juniors:
            excess = sum(shares.values()) - declared_supply_af
            if excess <= 0:
                break
            shares[c["id"]] = max(0, shares[c["id"]] - excess)
    return shares


# ---------------------------------------------------------------------------
# Allocation line balances and curtailment (PRD sections 3.3, 3.6)
# ---------------------------------------------------------------------------

def recompute_line(line):
    """allocation_remaining_balance: allocated + in - out - delivered - outstanding."""
    orders = orders_on_line(line["id"])
    delivered = sum(o["delivered_af"] for o in orders)
    outstanding = sum(o["ordered_af"] - o["delivered_af"] for o in orders
                      if o["fulfillment_status"] in ACTIVE_ORDER_STATES)
    remaining = (line["allocated_af"] + line["transfer_in_af"]
                 - line["transfer_out_af"] - delivered - outstanding)
    changed = (line["delivered_af"] != delivered) or (line["remaining_af"] != remaining)
    line["delivered_af"] = delivered
    line["remaining_af"] = remaining
    if changed:
        touch(line)


def curtailment_cascade(lines):
    """revision_curtailment_cascade: demote newest active orders first
    (created_at DESC, tie ordered_af DESC) until each line fits; then recompute."""
    for line in lines:
        while True:
            active = [o for o in orders_on_line(line["id"])
                      if o["fulfillment_status"] in ACTIVE_ORDER_STATES]
            over_commitment = line["delivered_af"] + sum(
                o["ordered_af"] - o["delivered_af"] for o in active)
            if over_commitment <= line["allocated_af"] or not active:
                break
            victim = max(active,
                         key=lambda o: (o["created_at"], o["ordered_af"], o["_seq"]))
            victim["fulfillment_status"] = "SHORTED"
            touch(victim)
        recompute_line(line)


# ---------------------------------------------------------------------------
# Reservoir releases (PRD section 3.5)
# ---------------------------------------------------------------------------

def release_volume_af(release_cfs, duration_days):
    """round_half_up(release_cfs * duration_days * 1.9835), per release at creation."""
    return rhu_int(Decimal(release_cfs) * Decimal(duration_days) * CFS_DAY_TO_AF)


def windows_intersect(a_start, a_end, b_start, b_end):
    """Half-open interval intersection: b_start < a_end and a_start < b_end."""
    return b_start < a_end and a_start < b_end


def days_touched(start, end):
    """Yield the midnight start of every calendar day intersecting [start, end)."""
    day = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    while day < end:
        yield day
        day += timedelta(days=1)


def day_load(reservoir_id, day_start, exclude_id=None):
    """Summed release_cfs of SCHEDULED/EXECUTED orders whose window touches the day."""
    day_end = day_start + timedelta(days=1)
    load = 0
    for r in DB["release_orders"].values():
        if r["reservoir_id"] != reservoir_id or r["id"] == exclude_id:
            continue
        if r["status"] not in ("SCHEDULED", "EXECUTED"):
            continue
        if windows_intersect(day_start, day_end, r["scheduled_start"], r["scheduled_end"]):
            load += r["release_cfs"]
    return load


# ---------------------------------------------------------------------------
# Hydropower revenue and repayment credits (PRD section 3.7)
# ---------------------------------------------------------------------------

def month_bounds(period_month):
    """[first instant of month, first instant of next month)."""
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def revenue_figures(reservoir, period_month, statuses, rate_cents_per_mwh):
    """hydropower_revenue: sum integer volumes, round MWh to 2dp, then cents."""
    start, end = month_bounds(period_month)
    volume = sum(
        r["volume_af"]
        for r in DB["release_orders"].values()
        if r["reservoir_id"] == reservoir["id"]
        and r["status"] in statuses
        and start <= r["scheduled_start"] < end
    )
    mwh = rhu_2dp(Decimal(volume) * reservoir["power_conversion_mwh_per_af"])
    revenue = rhu_int(mwh * Decimal(rate_cents_per_mwh))
    return mwh, revenue


def credit_distribution(settled_revenue_cents):
    """repayment_credit_distribution: per-contract round-half-up first
    (contract_number ASC), remainder to the largest outstanding balance
    (tie: contract_number ASC)."""
    contracts = sorted(DB["contracts"].values(), key=lambda c: c["contract_number"])
    credits = {c["id"]: 0 for c in contracts}
    total_obligation = sum(c["repayment_obligation_cents"] for c in contracts)
    if contracts and total_obligation > 0:
        for c in contracts:
            credits[c["id"]] = rhu_int(
                Decimal(settled_revenue_cents)
                * Decimal(c["repayment_obligation_cents"])
                / Decimal(total_obligation))
        remainder = settled_revenue_cents - sum(credits.values())
        if remainder != 0:
            target = min(contracts, key=lambda c: (
                -(c["repayment_obligation_cents"] - c["repaid_credits_cents"]),
                c["contract_number"]))
            credits[target["id"]] += remainder
    return credits
