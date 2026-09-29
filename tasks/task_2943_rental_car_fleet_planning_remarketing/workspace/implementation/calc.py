"""Derived counters and the six calculation rules of the PRD.

All money is whole cents with round-half-up on every rate multiplication; day
and month counts are integer floors; per-unit revenue is an integer floor.
"""

from decimal import Decimal

from errors import ApiError
from store import (
    dec,
    floor_div,
    parse_instant,
    round_half_up,
    round_half_up_4,
    store,
)

# -- calculation constants ---------------------------------------------
SECONDS_PER_DAY = 86400
DAYS_PER_DEPRECIATION_MONTH = 30

CHANNEL_HAUL_FACTOR = Decimal("1.15")
RECONDITION_OVERHEAD_PCT = Decimal("0.075")
FLOOR_PRICE_PCT = Decimal("0.75")
RECONDITION_ESTIMATE_PCT = Decimal("0.02")

SURCHARGE_TIER_1_CEILING_CENTS = 50000
SURCHARGE_TIER_2_CEILING_CENTS = 150000
SURCHARGE_PCT_TIER_1 = Decimal("0.12")
SURCHARGE_PCT_TIER_2 = Decimal("0.08")
SURCHARGE_PCT_TIER_3 = Decimal("0.05")
HANDLING_FLAT_CENTS = 7500
TRANSPORT_PAYBACK_DAYS = 45

TOTAL_LOSS_THRESHOLD_BP = 7000
RECOVERY_CAP_FACTOR = Decimal("1.25")

PLAN_SEASON_DAYS = {"PEAK": 92, "SHOULDER": 122, "OFF_PEAK": 151}
PREP_BAY_BUFFER_MINUTES = 60
MAX_REVISIONS = 3

IN_FLEETED_FLEET_STATUSES = ("IN_SERVICE", "IN_TRANSIT", "HELD_FOR_SALE", "SOLD")
OPEN_DAMAGE_STATUSES = ("REPORTED", "RECOVERY_PENDING")
NON_TERMINAL_ORDER_STATUSES = ("DRAFT", "PROPOSED", "REJECTED", "AUTHORIZED", "IN_TRANSIT")
NON_TERMINAL_CONSIGNMENT_STATUSES = ("DRAFT", "RECONDITION_PENDING", "LISTED")


# -- collection scans ---------------------------------------------------


def vehicles_of_allocation(allocation_id):
    return [v for v in store.vehicles.values() if v["allocation_id"] == allocation_id]


def allocations_of_plan(plan_id):
    return [a for a in store.allocations.values() if a["plan_id"] == plan_id]


def tasks_of_vehicle(vehicle_id):
    return [t for t in store.tasks.values() if t["vehicle_id"] == vehicle_id]


def orders_of_vehicle(vehicle_id):
    return [o for o in store.orders.values() if o["vehicle_id"] == vehicle_id]


def damage_events_of_vehicle(vehicle_id):
    return [d for d in store.damage_events.values() if d["vehicle_id"] == vehicle_id]


def consignments_of_vehicle(vehicle_id):
    return [c for c in store.consignments.values() if c["vehicle_id"] == vehicle_id]


def ledger_of_vehicle(vehicle_id):
    return [e for e in store.ledger.values() if e["vehicle_id"] == vehicle_id]


# -- derived counters (PRD 2.12) ---------------------------------------


def market_census(market_id):
    return sum(
        1
        for v in store.vehicles.values()
        if v["current_market_id"] == market_id and v["fleet_status"] == "IN_SERVICE"
    )


def allocation_in_fleeted_count(allocation):
    return sum(
        1
        for v in vehicles_of_allocation(allocation["id"])
        if v["fleet_status"] in IN_FLEETED_FLEET_STATUSES
    )


def allocation_created_vehicle_count(allocation):
    total = len(vehicles_of_allocation(allocation["id"]))
    return min(total, allocation["unit_count"])


def plan_allocated_unit_count(plan):
    return sum(
        a["unit_count"]
        for a in allocations_of_plan(plan["id"])
        if a["status"] in ("ORDERED", "PARTIALLY_INFLEETED", "INFLEETED")
    )


def plan_in_fleeted_unit_count(plan):
    total = 0
    for allocation in allocations_of_plan(plan["id"]):
        total += sum(
            1
            for v in vehicles_of_allocation(allocation["id"])
            if v["fleet_status"] in IN_FLEETED_FLEET_STATUSES
        )
    return total


def fill_ratio_bp(plan, allocated=None):
    if allocated is None:
        allocated = plan_allocated_unit_count(plan)
    planned = plan["planned_unit_count"]
    if planned <= 0:
        return 0
    return (allocated * 10000) // planned


def plan_posture(plan, allocated=None):
    ratio = fill_ratio_bp(plan, allocated)
    if ratio < 9000:
        return "OPEN"
    if ratio < 10000:
        return "RESTRICTED"
    return "FROZEN"


def total_recondition_cents(vehicle):
    return sum(
        e["amount_cents"]
        for e in ledger_of_vehicle(vehicle["id"])
        if e["entry_type"] in ("RECONDITION_COST", "RECONDITION_REVERSAL")
    )


def open_damage_cents(vehicle):
    return sum(
        d["estimate_cents"]
        for d in damage_events_of_vehicle(vehicle["id"])
        if d["status"] in OPEN_DAMAGE_STATUSES
    )


def active_policy(segment_id):
    for policy in store.policies.values():
        if policy["segment_id"] == segment_id and policy["status"] == "ACTIVE":
            return policy
    return None


# -- calculation 1: vehicle_residual_valuation -------------------------


def holding_days(vehicle):
    if not vehicle.get("in_service_at"):
        return 0
    start = parse_instant(vehicle["in_service_at"])
    end_raw = vehicle.get("held_for_sale_at")
    end = parse_instant(end_raw) if end_raw else store.now()
    elapsed = (end - start).total_seconds()
    if elapsed <= 0:
        return 0
    return int(elapsed // SECONDS_PER_DAY)


def valuation(vehicle, require_policy=True):
    """Both residual variants side by side (PRD 3.5)."""
    segment = store.segments[vehicle["segment_id"]]
    program = store.programs[vehicle["program_id"]]
    policy = active_policy(vehicle["segment_id"])
    if policy is None and require_policy:
        raise ApiError(
            "ERR_NO_ACTIVE_DEPRECIATION_POLICY",
            "No ACTIVE depreciation policy exists for the vehicle's segment.",
        )

    cap = vehicle["capitalized_cost_cents"]
    odo = vehicle["odometer_km"]
    days = holding_days(vehicle)
    months = days // DAYS_PER_DEPRECIATION_MONTH

    if policy is not None:
        time_dep = round_half_up(dec(cap) * dec(policy["monthly_depreciation_pct"]) * dec(months))
        mileage_dep = odo * policy["mileage_depreciation_cents_per_km"]
        floor_value = round_half_up(dec(cap) * dec(policy["floor_residual_pct"]))
        policy_nbv = max(cap - (time_dep + mileage_dep), floor_value)
    else:
        policy_nbv = None

    guarantee_base = round_half_up(dec(cap) * dec(program["repurchase_guarantee_pct"]))
    excess_km = max(0, odo - program["max_eligible_mileage_km"])
    excess_charge = excess_km * program["excess_mileage_charge_cents_per_km"]
    open_damage = open_damage_cents(vehicle)
    damage_deduction = min(open_damage, program["damage_deduction_cap_cents"])
    program_value = max(0, guarantee_base - excess_charge - damage_deduction)

    if program["program_type"] == "PROGRAM":
        applied_variant = "PROGRAM_GUARANTEE"
        nbv = program_value
    else:
        applied_variant = "POLICY_SCHEDULE"
        nbv = policy_nbv

    if odo > segment["mileage_band_hard_limit_km"]:
        band = "OVER_HARD"
    elif odo > segment["mileage_band_soft_limit_km"]:
        band = "OVER_SOFT"
    else:
        band = "WITHIN_SOFT"

    return {
        "holding_days": days,
        "holding_months": months,
        "odometer_km": odo,
        "capitalized_cost_cents": cap,
        "policy_net_book_value_cents": policy_nbv,
        "program_guaranteed_value_cents": program_value,
        "net_book_value_cents": nbv,
        "accumulated_depreciation_cents": (None if nbv is None else cap - nbv),
        "applied_variant": applied_variant,
        "mileage_band": band,
        "open_damage_cents": open_damage,
    }


def net_book_value(vehicle):
    """The applied variant's value, or None when it cannot be computed."""
    result = valuation(vehicle, require_policy=False)
    return result["net_book_value_cents"]


# -- calculation 2: consignment_net_proceeds ---------------------------


def channel_haul_cents(market):
    return round_half_up(
        dec(market["transport_hub_distance_km"])
        * dec(market["transfer_cost_per_km_cents"])
        * CHANNEL_HAUL_FACTOR
    )


def recondition_loaded_cents(actual):
    if actual is None:
        return None
    return round_half_up(dec(actual) * (Decimal(1) + RECONDITION_OVERHEAD_PCT))


def floor_price_cents(net_book_value_at_hold):
    return round_half_up(dec(net_book_value_at_hold) * FLOOR_PRICE_PCT)


def net_proceeds(consignment, channel, vehicle, market):
    gross = consignment["gross_proceeds_cents"]
    line_fee = round_half_up(dec(gross) * dec(channel["fee_pct"])) + channel["fixed_fee_cents"]
    line_transport = channel_haul_cents(market)
    loaded = recondition_loaded_cents(consignment.get("recondition_actual_cents"))
    line_recondition = 0 if loaded is None else loaded
    total_cost = line_fee + line_transport + line_recondition
    net = gross - total_cost
    return {
        "channel_fee_cents": line_fee,
        "transport_to_channel_cents": line_transport,
        "recondition_loaded_cents": loaded,
        "net_proceeds_cents": net,
        "gain_loss_cents": net - vehicle["net_book_value_at_hold_cents"],
    }


# -- calculation 3: fleet_plan_utilization_and_rpu ---------------------


def plan_performance(plan):
    season_days = PLAN_SEASON_DAYS[plan["season"]]
    candidates = []
    for allocation in allocations_of_plan(plan["id"]):
        if allocation["status"] == "CANCELLED":
            continue
        candidates.extend(vehicles_of_allocation(allocation["id"]))

    set_a = [
        v
        for v in candidates
        if v["fleet_status"] in ("ON_ORDER", "IN_FLEETING", "IN_SERVICE", "IN_TRANSIT")
    ]
    set_b = [v for v in candidates if v["fleet_status"] == "IN_SERVICE"]

    planned_units = plan["planned_unit_count"]
    rented_a = sum(v["rented_days_total"] for v in set_a)
    revenue_a = sum(v["revenue_to_date_cents"] for v in set_a)
    utilization_planned = round_half_up_4(dec(rented_a) / dec(planned_units * season_days))
    rpu_planned = floor_div(revenue_a, planned_units)

    rented_b = sum(v["rented_days_total"] for v in set_b)
    revenue_b = sum(v["revenue_to_date_cents"] for v in set_b)
    available_b = sum(v["available_days_total"] for v in set_b)
    if available_b == 0:
        utilization_actual = Decimal("0.0")
    else:
        utilization_actual = round_half_up_4(dec(rented_b) / dec(available_b))
    rpu_actual = 0 if len(set_b) == 0 else floor_div(revenue_b, len(set_b))

    allocated = plan_allocated_unit_count(plan)
    return {
        "planned_unit_count": planned_units,
        "allocated_unit_count": allocated,
        "in_fleeted_unit_count": plan_in_fleeted_unit_count(plan),
        "utilization_pct_planned": float(utilization_planned),
        "revenue_per_unit_cents_planned": rpu_planned,
        "utilization_pct_actual": float(utilization_actual),
        "revenue_per_unit_cents_actual": rpu_actual,
        "rpu_variance_cents": rpu_actual - plan["revenue_per_unit_target_cents"],
        "posture": plan_posture(plan, allocated),
        "season_days": season_days,
    }


# -- calculation 4: redistribution_transport_cost ----------------------


def transport_cost(distance_km, origin_market):
    base = distance_km * origin_market["transfer_cost_per_km_cents"]
    if base < SURCHARGE_TIER_1_CEILING_CENTS:
        pct = SURCHARGE_PCT_TIER_1
    elif base < SURCHARGE_TIER_2_CEILING_CENTS:
        pct = SURCHARGE_PCT_TIER_2
    else:
        pct = SURCHARGE_PCT_TIER_3
    surcharge = round_half_up(dec(base) * pct)
    return base + surcharge + HANDLING_FLAT_CENTS


def payback_ceiling_cents(segment):
    return round_half_up(dec(segment["baseline_daily_rate_cents"]) * dec(TRANSPORT_PAYBACK_DAYS))


# -- calculation 5: total loss / recovery waterfall --------------------


def total_loss_required(estimate_cents, baseline_cents):
    return estimate_cents * 10000 >= baseline_cents * TOTAL_LOSS_THRESHOLD_BP


def recovery_cap_cents(estimate_cents):
    return round_half_up(dec(estimate_cents) * RECOVERY_CAP_FACTOR)


def recovery_waterfall(recovered_cents, recondition_total, estimate_cents):
    bucket_1 = min(recovered_cents, recondition_total)
    bucket_2 = min(recovered_cents - bucket_1, max(0, estimate_cents - recondition_total))
    bucket_3 = recovered_cents - bucket_1 - bucket_2
    return bucket_1, bucket_2, bucket_3


# -- calculation 6: remarketing_channel_selection ----------------------


def channel_eligibility(vehicle, channel, days):
    """Returns None when eligible, else a short reason token."""
    if channel["status"] != "ACTIVE":
        return "SUSPENDED"
    segment = store.segments[vehicle["segment_id"]]
    program = store.programs[vehicle["program_id"]]
    if channel["code"] == "RETAIL_LOT":
        if vehicle["odometer_km"] > segment["mileage_band_hard_limit_km"]:
            return "MILEAGE"
    if channel["code"] == "PROGRAM_REPURCHASE":
        if program["program_type"] != "PROGRAM":
            return "PROGRAM_TYPE"
        if days < program["min_holding_days"]:
            return "MIN_HOLDING"
        if days > program["max_holding_days"]:
            return "MAX_HOLDING"
        if vehicle["odometer_km"] > program["max_eligible_mileage_km"]:
            return "MAX_MILEAGE"
        if vehicle["condition_status"] not in ("SOUND", "RECONDITIONED"):
            return "CONDITION"
    return None


def projected_net_proceeds(vehicle, channel, nbv, market, segment):
    gross = round_half_up(dec(nbv) * dec(channel["expected_proceeds_multiplier"]))
    fee = round_half_up(dec(gross) * dec(channel["fee_pct"])) + channel["fixed_fee_cents"]
    transport = channel_haul_cents(market)
    if channel["recondition_required"]:
        recondition = min(
            segment["recondition_cap_cents"],
            round_half_up(dec(vehicle["capitalized_cost_cents"]) * RECONDITION_ESTIMATE_PCT),
        )
    else:
        recondition = 0
    return gross - fee - transport - recondition


def channel_recommendation(vehicle):
    values = valuation(vehicle)
    nbv = values["net_book_value_cents"]
    days = values["holding_days"]
    segment = store.segments[vehicle["segment_id"]]
    market = store.markets[vehicle["current_market_id"]]

    scored = []
    excluded = []
    for channel in sorted(
        store.channels.values(), key=lambda c: (c["created_at"], c.get("_seq", 0))
    ):
        reason = channel_eligibility(vehicle, channel, days)
        if reason is not None:
            excluded.append(channel)
            continue
        net = projected_net_proceeds(vehicle, channel, nbv, market, segment)
        scored.append((channel, net))

    if not scored:
        raise ApiError(
            "ERR_NO_ELIGIBLE_CHANNEL",
            "No remarketing channel is eligible for this vehicle.",
        )

    scored.sort(
        key=lambda pair: (
            -pair[1],
            pair[0]["expected_days_to_sell"],
            pair[0]["created_at"],
            pair[0].get("_seq", 0),
        )
    )
    winner, winner_net = scored[0]
    return {
        "recommended_channel_id": winner["id"],
        "recommended_channel_code": winner["code"],
        "projected_net_proceeds_cents": winner_net,
        "eligible_channel_count": len(scored),
        "ranked_channel_codes": [pair[0]["code"] for pair in scored],
        "excluded_channel_codes": [channel["code"] for channel in excluded],
    }
