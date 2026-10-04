"""Business logic: DealerModelLine aggregates, allocation waterfall, pools,
incentive accrual (PRD §3.4, §3.5, §3.12, §3.13)."""
import math
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import get_store
from util import bump, new_entity, now_dt, parse_dt

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SALES_WEIGHT = 0.6
TURN_WEIGHT = 0.4
NEW_POINT_MONTHS = 6
NEW_POINT_FLOOR_UNITS = 2
PENALTY_PER_UNIT = 0.5
ZERO_SALES_SENTINEL = -1
TRADE_TTL_DAYS = 7
FILING_WINDOW_DAYS = 14


def _six_months() -> timedelta:
    """Six months as 184 days: matches the boundary design (2026-03-01 ->
    2026-09-01 is exactly six calendar months and 184 days)."""
    return timedelta(days=184)


def is_new_point(dealer: dict, reference_dt: datetime) -> bool:
    """Strict < 6 months between opened_on and the reference instant."""
    return (reference_dt - parse_dt(dealer["opened_on"])) < _six_months()


def _money2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# DealerModelLine (PRD §3.13)
# ---------------------------------------------------------------------------

def get_dml(dealer_id: str, model_line_id: str, create: bool = False):
    for dml in get_store("dealer_model_lines").values():
        if dml["dealer_id"] == dealer_id and dml["model_line_id"] == model_line_id:
            return dml
    if not create:
        return None
    dml = new_entity({
        "dealer_id": dealer_id,
        "model_line_id": model_line_id,
        "reported_sales_units": 0,
        "avg_inventory_units": 0,
        "days_supply": 0,
        "earned_credit_units": 0,
    })
    get_store("dealer_model_lines")[dml["id"]] = dml
    return dml


def _reference_run(model_line_id: str):
    """Latest closed (LOCKED) run for the line, else the latest run."""
    runs = [r for r in get_store("allocation_runs").values()
            if r["model_line_id"] == model_line_id]
    if not runs:
        return None
    runs.sort(key=lambda r: (r["created_at"], r["id"]))
    locked = [r for r in runs if r["status"] == "LOCKED"]
    return locked[-1] if locked else runs[-1]


def count_sales_in_window(dealer_id: str, model_line_id: str,
                          lookback_start, lookback_end) -> int:
    start = parse_dt(lookback_start)
    end = parse_dt(lookback_end)
    count = 0
    for order in get_store("vehicle_orders").values():
        if (order["dealer_id"] == dealer_id
                and order["model_line_id"] == model_line_id
                and order["state"] == "DELIVERED"
                and order.get("delivered_at") is not None
                and order.get("retrofit_of_order_id") is None):
            delivered = parse_dt(order["delivered_at"])
            if start <= delivered < end:
                count += 1
    return count


def count_avg_inventory(dealer_id: str, model_line_id: str) -> int:
    count = 0
    for order in get_store("vehicle_orders").values():
        if (order["dealer_id"] == dealer_id
                and order["model_line_id"] == model_line_id
                and order["state"] in ("SCHEDULED", "BUILT")
                and order.get("retrofit_of_order_id") is None):
            count += 1
    return count


def count_delivered(dealer_id: str, model_line_id: str) -> int:
    count = 0
    for order in get_store("vehicle_orders").values():
        if (order["dealer_id"] == dealer_id
                and order["model_line_id"] == model_line_id
                and order["state"] == "DELIVERED"
                and order.get("retrofit_of_order_id") is None):
            count += 1
    return count


def recompute_dml(dealer_id: str, model_line_id: str) -> None:
    dml = get_dml(dealer_id, model_line_id, create=True)
    run = _reference_run(model_line_id)
    avg_inv = count_avg_inventory(dealer_id, model_line_id)
    # reported_sales_units: chronological inclusion by delivered_at — every
    # delivered order for the line (the lookback window restricts the
    # allocation_share sales input, not this running ledger figure).
    sales = count_delivered(dealer_id, model_line_id)
    if run is not None:
        lookback_days = (parse_dt(run["lookback_end"]) - parse_dt(run["lookback_start"])).days
    else:
        lookback_days = 0
    if sales == 0:
        days_supply = ZERO_SALES_SENTINEL if avg_inv > 0 else 0
    elif lookback_days <= 0:
        days_supply = ZERO_SALES_SENTINEL
    else:
        daily = sales / lookback_days
        days_supply = float(Decimal(str(avg_inv / daily)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    changed = (
        dml["reported_sales_units"] != sales
        or dml["avg_inventory_units"] != avg_inv
        or dml["days_supply"] != days_supply
    )
    dml["reported_sales_units"] = sales
    dml["avg_inventory_units"] = avg_inv
    dml["days_supply"] = days_supply
    if changed:
        bump(dml)


# ---------------------------------------------------------------------------
# DealerAllocation helpers (PRD §3.5)
# ---------------------------------------------------------------------------

def get_da(run_id: str, dealer_id: str):
    for da in get_store("dealer_allocations").values():
        if da["run_id"] == run_id and da["dealer_id"] == dealer_id:
            return da
    return None


def _round_half_up_int(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_da_pools(da: dict, run: dict, dealer: dict) -> None:
    """final_units (with new-point floor) + retail_reserved_units."""
    straight = da["base_units"] + da["adjustment_units"]
    published_at = run.get("published_at")
    if published_at is not None and is_new_point(dealer, parse_dt(published_at)):
        final_units = max(straight, NEW_POINT_FLOOR_UNITS)
    else:
        final_units = straight
    reserved = _round_half_up_int(final_units * run["retail_priority_pct"] / 100)
    if da["final_units"] != final_units or da["retail_reserved_units"] != reserved:
        da["final_units"] = final_units
        da["retail_reserved_units"] = reserved
        bump(da)


def da_remaining_total(da: dict) -> int:
    return da["final_units"] - da["consumed_units"]


def da_retail_pool(da: dict) -> int:
    return da["retail_reserved_units"] - da["retail_consumed_units"]


def da_stock_pool(da: dict) -> int:
    return ((da["final_units"] - da["retail_reserved_units"])
            - (da["consumed_units"] - da["retail_consumed_units"]))


# ---------------------------------------------------------------------------
# Turn-and-earn waterfall (PRD §3.4)
# ---------------------------------------------------------------------------

def _eligible_dealers(published_at=None):
    dealers = []
    regions = get_store("regions")
    for dealer in get_store("dealers").values():
        region = regions.get(dealer["region_id"])
        if dealer["status"] == "ACTIVE" and region is not None and region["status"] == "ACTIVE":
            dealers.append(dealer)
    if published_at is not None:
        # Turn-and-earn requires history: a dealer within (or exactly at) the
        # six-month new-point window at publish draws no waterfall share; new
        # points are stocked purely via the NEW_POINT floor (§3.5).
        ref = parse_dt(published_at) if isinstance(published_at, str) else published_at
        dealers = [d for d in dealers
                   if (ref - parse_dt(d["opened_on"])) > _six_months()]
    return dealers


def compute_allocation_shares(run: dict) -> dict:
    """Return dealer_id -> (base_units_taken, want). Provisional variant."""
    pool = run["base_units"]
    # Materialize DealerModelLine rows for every dealer holding an allocation
    # on this run so the aggregate is readable right after publish (§3.13).
    for da in get_store("dealer_allocations").values():
        if da["run_id"] == run["id"]:
            get_dml(da["dealer_id"], run["model_line_id"], create=True)
    dealers = _eligible_dealers(run.get("published_at") or None)
    if not dealers:
        return {}
    sales = {}
    inv = {}
    turn = {}
    for dealer in dealers:
        dml = get_dml(dealer["id"], run["model_line_id"])
        s = count_sales_in_window(dealer["id"], run["model_line_id"],
                                  run["lookback_start"], run["lookback_end"])
        i = dml["avg_inventory_units"] if dml else 0
        sales[dealer["id"]] = s
        inv[dealer["id"]] = i
        turn[dealer["id"]] = s / max(i, 1)
    sum_sales = sum(sales.values())
    sum_turn = sum(turn.values())
    n = len(dealers)
    raw = {}
    for dealer in dealers:
        if sum_sales == 0 and sum_turn == 0:
            r = 1 / n if n else 0.0
        else:
            sales_term = (sales[dealer["id"]] / sum_sales) if sum_sales else 0.0
            turn_term = (turn[dealer["id"]] / sum_turn) if sum_turn else 0.0
            r = SALES_WEIGHT * sales_term + TURN_WEIGHT * turn_term
        # Raw scores at 6 decimal places round_half_up before waterfall.
        raw[dealer["id"]] = float(Decimal(str(r)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP))

    def sort_key(dealer):
        return (-raw[dealer["id"]], parse_dt(dealer["opened_on"]),
                parse_dt(dealer["created_at"]))

    ordered = sorted(dealers, key=sort_key)
    remaining = pool
    result = {}
    for dealer in ordered:
        dml = get_dml(dealer["id"], run["model_line_id"])
        earned = dml["earned_credit_units"] if dml else 0
        want = math.floor(raw[dealer["id"]] * pool) + earned
        taken = min(want, remaining)
        taken = max(taken, 0)
        remaining -= taken
        result[dealer["id"]] = (int(taken), want)
    return result


def publish_recompute(run: dict) -> None:
    """Provisional variant: write base_units/final/reserved per child."""
    shares = compute_allocation_shares(run)
    for da in get_store("dealer_allocations").values():
        if da["run_id"] != run["id"]:
            continue
        dealer = get_store("dealers").get(da["dealer_id"])
        taken, _want = shares.get(da["dealer_id"], (0, 0))
        da["base_units"] = taken
        recompute_da_pools(da, run, dealer)


def lock_recompute(run: dict) -> None:
    """Final variant: surplus = want - consumed -> earned_credit_units.
    base_units is NOT changed."""
    shares = compute_allocation_shares(run)
    for da in get_store("dealer_allocations").values():
        if da["run_id"] != run["id"]:
            continue
        _taken, want = shares.get(da["dealer_id"], (0, 0))
        surplus = want - da["consumed_units"]
        dml = get_dml(da["dealer_id"], run["model_line_id"], create=True)
        dml["earned_credit_units"] = _money2(surplus)
        bump(dml)


# ---------------------------------------------------------------------------
# Commodity cap (PRD §3.6, SCAFFOLD commodity_cap)
# ---------------------------------------------------------------------------

def active_restriction_for(commodity_id: str, model_line_id: str):
    """The ACTIVE restriction for the pair, if any (sweep first)."""
    from util import sweep_all_restrictions
    sweep_all_restrictions()
    for r in get_store("commodity_restrictions").values():
        if (r["commodity_id"] == commodity_id
                and r["model_line_id"] == model_line_id
                and r["status"] == "ACTIVE"):
            commodity = get_store("commodities").get(r["commodity_id"])
            if commodity is not None and commodity["status"] == "CONSTRAINED":
                return r
    return None


def commodity_cap_admits(dealer_id: str, model_line_id: str, run_id: str,
                         restriction: dict, commodity_code: str) -> bool:
    """Pre-accept evaluation: F + 1 <= floor((A + 1) * rate / 100)."""
    rate = restriction["install_rate_pct"]
    if rate >= 100:
        return True
    A = 0
    F = 0
    for order in get_store("vehicle_orders").values():
        if (order["dealer_id"] == dealer_id
                and order["model_line_id"] == model_line_id
                and order["run_id"] == run_id
                and order["state"] in ("ACCEPTED", "SCHEDULED", "BUILT", "DELIVERED")
                and order.get("retrofit_of_order_id") is None):
            A += 1
            if commodity_code in (order["configuration"] or {}).get("commodity_codes", []):
                F += 1
    return (F + 1) <= ((A + 1) * rate) // 100


# ---------------------------------------------------------------------------
# Incentive accrual (PRD §3.12)
# ---------------------------------------------------------------------------

def compute_accrual(program: dict, dealer_id: str) -> int:
    start = parse_dt(program["window_start"])
    end = parse_dt(program["window_end"])
    line = program["model_line_id"]
    delivered = []
    for order in get_store("vehicle_orders").values():
        if (order["dealer_id"] == dealer_id
                and order["model_line_id"] == line
                and order["state"] == "DELIVERED"
                and order.get("delivered_at") is not None
                and order.get("retrofit_of_order_id") is None):
            d = parse_dt(order["delivered_at"])
            if start <= d < end:
                delivered.append(order)
    params = program["params"] or {}
    if program["kind"] == "AGED_INVENTORY_CREDIT":
        total = 0
        t1_age = params.get("age_threshold_days", 0)
        t1_credit = params.get("credit_per_unit_cents", 0)
        t2_age = params.get("tier2_age_days", 0)
        t2_credit = params.get("tier2_credit_per_unit_cents", 0)
        for order in delivered:
            scheduled_at = order.get("scheduled_at")
            if scheduled_at is None:
                continue
            age_days = (parse_dt(order["delivered_at"]) - parse_dt(scheduled_at)).days
            if age_days >= t2_age:
                total += t2_credit
            elif age_days >= t1_age:
                total += t1_credit
        return total
    # VOLUME_BONUS — marginal tiers.
    s = len(delivered)
    t1 = params.get("tier1_threshold", 0)
    t1_bonus = params.get("tier1_bonus_cents", 0)
    t2 = params.get("tier2_threshold", 0)
    t2_bonus = params.get("tier2_bonus_cents", 0)
    bonus = 0
    if s > t1:
        bonus += (min(s, t2) - t1) * t1_bonus
    if s > t2:
        bonus += (s - t2) * t2_bonus
    return bonus
