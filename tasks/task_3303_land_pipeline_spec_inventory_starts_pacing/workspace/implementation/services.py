"""Business logic: lazy defaulting, pacing math, pricing, posture, serializers."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, iso3
from helpers import dt_or_none, iso_or_none, clock

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGE_MULTIPLIERS = {
    "PERMITTED": Decimal("1.00"),
    "FOUNDATION": Decimal("1.00"),
    "FRAME": Decimal("1.01"),
    "DRYWALL": Decimal("1.02"),
    "COMPLETE": Decimal("1.03"),
    "CLOSED": Decimal("1.03"),
}

CAP_PCT = {
    "PLANNING": Decimal("0.06"),
    "OPEN_FOR_SALES": Decimal("0.06"),
    "SELLING_OUT": Decimal("0.06"),
    "CLOSE_OUT": Decimal("0.10"),
    "CLOSED": Decimal("0.10"),
}

QUARTER_DAYS = 91
ESCALATION_RATE = Decimal("0.01")
ABSORPTION_FLOOR = 1.0
OVERHELD_THRESHOLD = 4.0
STARVED_THRESHOLD = 1.5
INCENTIVE_BUFFER = timedelta(days=7)
TRAILING_WINDOW = timedelta(days=90)


def round_half_up_int(x):
    """Round a Decimal to the nearest integer, half-up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lazy defaulting (takedowns / option contracts)
# ---------------------------------------------------------------------------

def apply_lazy_defaults():
    """Flip SCHEDULED takedowns past window_end to DEFAULTED and cascade
    ACTIVE contracts with any DEFAULTED takedown to DEFAULTED.
    Triggered on reads of takedowns/contracts and on execute attempts.
    NOT triggered by the clock-set endpoint itself."""
    now = clock()
    for td in db.takedowns.values():
        if td["state"] == "SCHEDULED" and now > dt_or_none(td["window_end"]):
            td["state"] = "DEFAULTED"
    for oc in db.option_contracts.values():
        if oc["state"] == "ACTIVE":
            if any(
                td["option_contract_id"] == oc["id"] and td["state"] == "DEFAULTED"
                for td in db.takedowns.values()
            ):
                oc["state"] = "DEFAULTED"


# ---------------------------------------------------------------------------
# Community computed counters
# ---------------------------------------------------------------------------

def community_contracts(community_id):
    home_ids = [h["id"] for h in db.homes.values() if h["community_id"] == community_id]
    return [sc for sc in db.sales_contracts.values() if sc["home_id"] in home_ids]


def absorption_metrics(community_id):
    """Return (closed_in_window, open_pipeline, trailing_rate, forward_rate).
    Rates are exact rationals: closed/3.0 etc."""
    now = clock()
    window_start = now - TRAILING_WINDOW
    closed = 0
    open_pipeline = 0
    for sc in community_contracts(community_id):
        if sc["state"] == "CLOSED" and sc.get("closed_at"):
            closed_at = dt_or_none(sc["closed_at"])
            if window_start <= closed_at <= now:
                closed += 1
        if sc["state"] in ("PENDING", "APPROVED"):
            open_pipeline += 1
    trailing = closed / 3.0
    forward = (closed + open_pipeline) / 3.0
    return closed, open_pipeline, trailing, forward


def posture_of(community_id):
    """Return (standing, trailing, forward, months_of_supply, posture)."""
    standing = sum(
        1 for h in db.homes.values()
        if h["community_id"] == community_id and h["sales_status"] == "UNSOLD"
    )
    _, _, trailing, forward = absorption_metrics(community_id)
    effective = max(trailing, ABSORPTION_FLOOR)
    mos = standing / effective
    if mos >= OVERHELD_THRESHOLD:
        posture = "OVERHELD"
    elif mos < STARVED_THRESHOLD:
        posture = "STARVED"
    else:
        posture = "NORMAL"
    return standing, trailing, forward, mos, posture


def current_published_plan(community_id):
    """The PUBLISHED pacing plan whose closed period covers the clock, if any."""
    now = clock()
    covering = [
        p for p in db.pacing_plans.values()
        if p["community_id"] == community_id
        and p["state"] == "PUBLISHED"
        and dt_or_none(p["period_start"]) <= now <= dt_or_none(p["period_end"])
    ]
    if not covering:
        return None
    covering.sort(key=lambda p: (p["created_at"], p["id"]))
    return covering[-1]


def latest_published_plan(community_id):
    plans = [
        p for p in db.pacing_plans.values()
        if p["community_id"] == community_id and p["state"] == "PUBLISHED"
    ]
    if not plans:
        return None
    plans.sort(key=lambda p: (p["created_at"], p["id"]))
    return plans[-1]


def starts_this_period(community_id):
    plan = latest_published_plan(community_id)
    if plan is None:
        return 0
    start = dt_or_none(plan["period_start"])
    end = dt_or_none(plan["period_end"])
    count = 0
    for h in db.homes.values():
        if h["community_id"] != community_id:
            continue
        created = dt_or_none(h["created_at"])
        if start <= created <= end:
            count += 1
    return count


def select_framing_commitment(community_id):
    """Eligible pool: FRAMING partner, this community, period half-open covers
    clock, remaining_units > 0. Rank period_start ASC then created_at ASC."""
    now = clock()
    pool = []
    for cc in db.capacity_commitments.values():
        if cc["community_id"] != community_id:
            continue
        tp = db.trade_partners.get(cc["trade_partner_id"])
        if tp is None or tp["trade"] != "FRAMING":
            continue
        if not (dt_or_none(cc["period_start"]) <= now < dt_or_none(cc["period_end"])):
            continue
        remaining = cc["committed_units"] - cc["allocated_units"]
        if remaining <= 0:
            continue
        pool.append((dt_or_none(cc["period_start"]), cc["created_at"], cc["id"], cc))
    if not pool:
        return None
    pool.sort(key=lambda t: (t[0], t[1], t[2]))
    return pool[0][3]


def capacity_remaining(community_id):
    cc = select_framing_commitment(community_id)
    if cc is None:
        return 0
    return cc["committed_units"] - cc["allocated_units"]


def quota_remaining(community_id):
    plan = current_published_plan(community_id)
    if plan is None:
        return 0
    return max(0, plan["max_starts"] - starts_this_period(community_id))


def inventory_allowance(community_id):
    standing, trailing, _, _, posture = posture_of(community_id)
    community = db.communities.get(community_id)
    if community is None:
        return 0
    effective = max(trailing, ABSORPTION_FLOOR)
    allowance = max(
        0, math.ceil(effective * community["months_supply_target"]) - standing
    )
    if posture == "STARVED":
        allowance = max(allowance, 1)
    return allowance


def starts_authorization(community_id):
    """Return (max_starts_remaining, starts_halted)."""
    msr = min(
        capacity_remaining(community_id),
        quota_remaining(community_id),
        inventory_allowance(community_id),
    )
    return msr, msr == 0


# ---------------------------------------------------------------------------
# Incentive status and stacking
# ---------------------------------------------------------------------------

def incentive_status(inc):
    if inc["cancelled"]:
        return "CANCELLED"
    now = clock()
    ws = dt_or_none(inc["window_start"])
    we = dt_or_none(inc["window_end"])
    if ws <= now <= we:
        return "ACTIVE"
    if inc.get("auto_activate_on_overheld") and now <= we:
        _, _, _, _, posture = posture_of(inc["community_id"])
        if posture == "OVERHELD":
            return "ACTIVE"
    if now < ws:
        return "SCHEDULED"
    return "EXPIRED"


def applicable_active_incentives(home):
    community_id = home["community_id"]
    series = db.product_series.get(home["product_series_id"])
    series_code = series["series_code"] if series else None
    out = []
    for inc in db.incentives.values():
        if inc["community_id"] != community_id:
            continue
        if incentive_status(inc) != "ACTIVE":
            continue
        if inc["series_code"] is not None and inc["series_code"] != series_code:
            continue
        out.append(inc)
    out.sort(key=lambda i: (i["created_at"], i["id"]))
    return out


def compute_home_pricing(home):
    """Compute adjusted_price_cents, stacked_incentive_cents,
    net_effective_price_cents. Returns a dict of the three values."""
    gross = home["base_price_cents"] + home.get("lot_premium_cents", 0)
    multiplier = STAGE_MULTIPLIERS[home["build_stage"]]
    adjusted = round_half_up_int(Decimal(gross) * multiplier)

    community = db.communities.get(home["community_id"])
    phase = community["phase"] if community else "PLANNING"
    cap = round_half_up_int(CAP_PCT[phase] * Decimal(adjusted))

    raw_stack = 0
    for inc in applicable_active_incentives(home):
        if inc["type"] in ("PRICE_CUT", "CLOSING_COST_CREDIT"):
            component = int(inc["value_cents"])
        else:  # RATE_BUYDOWN
            # value_pct arrives as a JSON number (a float after parsing). PRD
            # §2.8 pins exact money math, so reconstruct the client's intended
            # decimal from the float's shortest round-trip representation
            # (repr(0.004700000000000001) is '0.004700000000000001', and the
            # JSON text round-trips through the same shortest-repr algorithm).
            component = round_half_up_int(
                Decimal(repr(inc["value_pct"])) * Decimal(adjusted)
            )
        raw_stack += component
    stacked = min(raw_stack, cap)
    return {
        "gross_price_cents": gross,
        "adjusted_price_cents": adjusted,
        "stacked_incentive_cents": stacked,
        "net_effective_price_cents": adjusted - stacked,
    }


def refresh_community_home_pricing(community_id):
    for home in db.homes.values():
        if home["community_id"] == community_id:
            home.update(compute_home_pricing(home))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_land_parcel(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "market_code": p["market_code"],
        "acres": p["acres"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_option_contract(oc):
    return {
        "id": oc["id"],
        "land_parcel_id": oc["land_parcel_id"],
        "option_fee_cents": oc["option_fee_cents"],
        "earnest_money_cents": oc["earnest_money_cents"],
        "total_lots": oc["total_lots"],
        "lot_base_price_cents": oc["lot_base_price_cents"],
        "state": oc["state"],
        "executed_at": oc["executed_at"],
        "lots_taken_down": oc["lots_taken_down"],
        "cure_fee_cents": round_half_up_int(Decimal(oc["option_fee_cents"]) * Decimal("0.10")),
        "created_at": oc["created_at"],
        "updated_at": oc["updated_at"],
        "version": oc["version"],
    }


def ser_takedown(td):
    return {
        "id": td["id"],
        "option_contract_id": td["option_contract_id"],
        "community_id": td["community_id"],
        "lot_count": td["lot_count"],
        "window_start": td["window_start"],
        "window_end": td["window_end"],
        "state": td["state"],
        "executed_at": td["executed_at"],
        "escalated_lot_price_cents": td.get("escalated_lot_price_cents"),
        "credit_per_lot_cents": td.get("credit_per_lot_cents"),
        "net_due_per_lot_cents": td.get("net_due_per_lot_cents"),
        "total_net_due_cents": td.get("total_net_due_cents"),
        "created_at": td["created_at"],
        "updated_at": td["updated_at"],
        "version": td["version"],
    }


def ser_community(c):
    standing, trailing, forward, mos, posture = posture_of(c["id"])
    msr, halted = starts_authorization(c["id"])
    return {
        "id": c["id"],
        "name": c["name"],
        "market_code": c["market_code"],
        "absorption_target_per_month": c["absorption_target_per_month"],
        "months_supply_target": c["months_supply_target"],
        "phase": c["phase"],
        "standing_spec_count": standing,
        "starts_this_period": starts_this_period(c["id"]),
        "lifetime_closed_sales": sum(
            1 for sc in community_contracts(c["id"]) if sc["state"] == "CLOSED"
        ),
        "trailing_absorption_rate": trailing,
        "forward_pace_rate": forward,
        "months_of_supply": mos,
        "posture": posture,
        "max_starts_remaining": msr,
        "starts_halted": halted,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_product_series(ps):
    return {
        "id": ps["id"],
        "community_id": ps["community_id"],
        "series_code": ps["series_code"],
        "min_price_cents": ps["min_price_cents"],
        "max_price_cents": ps["max_price_cents"],
        "created_at": ps["created_at"],
        "updated_at": ps["updated_at"],
        "version": ps["version"],
    }


def ser_lot(lot):
    return {
        "id": lot["id"],
        "community_id": lot["community_id"],
        "source_takedown_id": lot["source_takedown_id"],
        "state": lot["state"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def ser_home(h):
    return {
        "id": h["id"],
        "community_id": h["community_id"],
        "lot_id": h["lot_id"],
        "product_series_id": h["product_series_id"],
        "base_price_cents": h["base_price_cents"],
        "lot_premium_cents": h.get("lot_premium_cents", 0),
        "build_stage": h["build_stage"],
        "sales_status": h["sales_status"],
        "gross_price_cents": h["gross_price_cents"],
        "adjusted_price_cents": h["adjusted_price_cents"],
        "stacked_incentive_cents": h["stacked_incentive_cents"],
        "net_effective_price_cents": h["net_effective_price_cents"],
        "completed_at": h.get("completed_at"),
        "cycle_time_days": h.get("cycle_time_days"),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def ser_sales_contract(sc):
    return {
        "id": sc["id"],
        "home_id": sc["home_id"],
        "buyer_name": sc["buyer_name"],
        "contract_price_cents": sc["contract_price_cents"],
        "state": sc["state"],
        "approved_at": sc.get("approved_at"),
        "closed_at": sc.get("closed_at"),
        "renegotiation_count": sc.get("renegotiation_count", 0),
        "created_at": sc["created_at"],
        "updated_at": sc["updated_at"],
        "version": sc["version"],
    }


def ser_incentive(inc):
    return {
        "id": inc["id"],
        "community_id": inc["community_id"],
        "type": inc["type"],
        "value_cents": inc.get("value_cents"),
        "value_pct": inc.get("value_pct"),
        "series_code": inc.get("series_code"),
        "window_start": inc["window_start"],
        "window_end": inc["window_end"],
        "auto_activate_on_overheld": inc.get("auto_activate_on_overheld", False),
        "cancelled": inc["cancelled"],
        "status": incentive_status(inc),
        "created_at": inc["created_at"],
        "updated_at": inc["updated_at"],
        "version": inc["version"],
    }


def ser_trade_partner(tp):
    return {
        "id": tp["id"],
        "name": tp["name"],
        "trade": tp["trade"],
        "created_at": tp["created_at"],
        "updated_at": tp["updated_at"],
        "version": tp["version"],
    }


def ser_capacity_commitment(cc):
    return {
        "id": cc["id"],
        "trade_partner_id": cc["trade_partner_id"],
        "community_id": cc["community_id"],
        "period_start": cc["period_start"],
        "period_end": cc["period_end"],
        "committed_units": cc["committed_units"],
        "allocated_units": cc["allocated_units"],
        "remaining_units": cc["committed_units"] - cc["allocated_units"],
        "created_at": cc["created_at"],
        "updated_at": cc["updated_at"],
        "version": cc["version"],
    }


def ser_pacing_plan(p):
    return {
        "id": p["id"],
        "community_id": p["community_id"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "max_starts": p["max_starts"],
        "state": p["state"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
