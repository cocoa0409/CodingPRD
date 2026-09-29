"""The twelve normative calculations (PRD sections 2.6 and 3.x).

All money is integer cents and every rounding step uses Decimal with
ROUND_HALF_UP. Python's builtin round() is never used.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from db import db, parse_ts, sort_key_created

D = Decimal


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_div(numerator, denominator):
    return int((dec(numerator) / dec(denominator)).to_integral_value(rounding=ROUND_CEILING))


def floor_dec(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def as_float(value, places):
    return float(rhu(value, places))


# --------------------------------------------------------------- calculation 1
# delivery_fee

BASE_FEE_CENTS = 349
PER_100M_CENTS = 22
PAYLOAD_TIER_CENTS = {"SMALL": 0, "MEDIUM": 120, "LARGE": 260}
PAYLOAD_TIER_UPPER_LITERS = {"SMALL": D("15.0"), "MEDIUM": D("30.0"), "LARGE": D("45.0")}
URGENCY_WINDOW_MINUTES = 45
URGENCY_SURCHARGE_CENTS = 180
CROSSING_FEE_CENTS = 35
INTERVENTION_SURCHARGE_CENTS = 95
BLOCKAGE_CREDIT_CENTS_PER_MIN = 8
BLOCKAGE_CREDIT_CAP_FRACTION = D("0.40")
MERCHANT_GRADE_DISCOUNT = {"STANDARD": D("0.00"), "PREFERRED": D("0.05"), "ANCHOR": D("0.12")}


def payload_tier(payload_liters):
    value = dec(payload_liters)
    if value <= PAYLOAD_TIER_UPPER_LITERS["SMALL"]:
        return "SMALL"
    if value <= PAYLOAD_TIER_UPPER_LITERS["MEDIUM"]:
        return "MEDIUM"
    return "LARGE"


def urgency_flag(created_at_iso, promised_by_iso):
    delta = parse_ts(promised_by_iso) - parse_ts(created_at_iso)
    return delta.total_seconds() <= URGENCY_WINDOW_MINUTES * 60


def delivery_fee(
    distance_m,
    crossings,
    interventions,
    blocked_minutes,
    tier,
    urgency,
    merchant_grade,
):
    distance_units = ceil_div(distance_m, 100)
    gross = (
        D(BASE_FEE_CENTS)
        + D(distance_units) * D(PER_100M_CENTS)
        + D(PAYLOAD_TIER_CENTS[tier])
        + (D(URGENCY_SURCHARGE_CENTS) if urgency else D(0))
        + D(int(crossings)) * D(CROSSING_FEE_CENTS)
        + D(int(interventions)) * D(INTERVENTION_SURCHARGE_CENTS)
    )
    cap = D(floor_dec(gross * BLOCKAGE_CREDIT_CAP_FRACTION))
    credit = D(int(blocked_minutes)) * D(BLOCKAGE_CREDIT_CENTS_PER_MIN)
    if credit > cap:
        credit = cap
    discount = MERCHANT_GRADE_DISCOUNT[merchant_grade]
    return rhu_int((gross - credit) * (D(1) - discount))


def quote_at_order(zone, tier, urgency, merchant_grade):
    return delivery_fee(
        zone["planning_haul_m"],
        zone["planning_crossings"],
        0,
        0,
        tier,
        urgency,
        merchant_grade,
    )


def settlement_at_completion(mission, tier, urgency, merchant_grade):
    return delivery_fee(
        mission["traveled_distance_m"],
        mission["traversed_crossing_count"],
        mission["intervention_count"],
        mission["blocked_minutes"],
        tier,
        urgency,
        merchant_grade,
    )


# --------------------------------------------------------------- calculation 2
# robot_autonomy_index

START_INDEX = 100
INTERVENTION_PENALTY = 6
ESCALATION_PENALTY_EXTRA = 4
CLEAN_MISSION_CREDIT = 2
ROLLING_WINDOW_MISSIONS = 5
ROLLING_DECAY_FACTOR = D("0.85")
INDEX_FLOOR = 40
INDEX_CEILING = 100
DISPATCH_ELIGIBLE_MIN_INDEX = 70

TERMINAL_MISSION_STATES = ("COMPLETED", "ABORTED")


def _clamp_index(value):
    if value < D(INDEX_FLOOR):
        value = D(INDEX_FLOOR)
    if value > D(INDEX_CEILING):
        value = D(INDEX_CEILING)
    return int(rhu(value, 0))


def rolling_autonomy_index(robot):
    missions = [
        m
        for m in db.missions.values()
        if m["robot_id"] == robot["id"] and m["mission_state"] in TERMINAL_MISSION_STATES
    ]
    missions.sort(key=lambda m: (m["created_at"], m["_seq"]))
    missions.sort(key=lambda m: (m["completed_at_utc"] or ""), reverse=True)
    window = missions[:ROLLING_WINDOW_MISSIONS]
    total = D(START_INDEX)
    for index, mission in enumerate(window):
        weight = ROLLING_DECAY_FACTOR ** index
        term = D(INTERVENTION_PENALTY) * D(mission["intervention_count"]) + D(
            ESCALATION_PENALTY_EXTRA
        ) * D(mission["escalation_count"])
        credit = D(CLEAN_MISSION_CREDIT) if mission["intervention_count"] == 0 else D(0)
        total += weight * (credit - term)
    return _clamp_index(total)


def lifetime_autonomy_index(robot):
    total = (
        D(START_INDEX)
        - (
            D(INTERVENTION_PENALTY) * D(robot["lifetime_intervention_count"])
            + D(ESCALATION_PENALTY_EXTRA) * D(robot["lifetime_escalation_count"])
        )
        + D(CLEAN_MISSION_CREDIT) * D(robot["clean_mission_count"])
    )
    return _clamp_index(total)


# --------------------------------------------------------------- calculation 3
# crossing_risk_score

CONTROL_ADJUSTMENT = {"NONE": D(0), "SIGNALIZED": D(-12), "UNSIGNALIZED": D(10), "MIDBLOCK": D(22)}
FLOW_COEFFICIENT = D("1.4")
FLOW_CAP = D(28)
GRADE_THRESHOLD_PCT = D("5.0")
GRADE_COEFFICIENT = D("3.0")
RAMP_CREDIT = D(-6)


def sightline_term(sightline_m):
    value = dec(sightline_m)
    if value >= D(30):
        return D(0)
    if value >= D(20):
        return D(8)
    if value >= D(10):
        return D(18)
    return D(30)


def crossing_risk_score(segment):
    total = sightline_term(segment["sightline_m"])
    flow = FLOW_COEFFICIENT * dec(segment["pedestrian_flow_per_min"])
    if flow > FLOW_CAP:
        flow = FLOW_CAP
    total += flow
    total += CONTROL_ADJUSTMENT[segment["crossing_control"]]
    grade_excess = dec(segment["surface_grade_pct"]) - GRADE_THRESHOLD_PCT
    if grade_excess < D(0):
        grade_excess = D(0)
    total += grade_excess * GRADE_COEFFICIENT
    if segment["curb_ramp_present"]:
        total += RAMP_CREDIT
    if total < D(0):
        total = D(0)
    if total > D(100):
        total = D(100)
    return float(rhu(total, 1))


# --------------------------------------------------------------- calculation 4
# route_clearance_margin

CLEARANCE_BUFFER_CM = D(12)


def route_clearance_margin(segments, robot):
    margins = [
        dec(segment["measured_clearance_cm"]) - dec(robot["width_cm"]) - CLEARANCE_BUFFER_CM
        for segment in segments
    ]
    return float(rhu(min(margins), 1))


# --------------------------------------------------------------- calculation 5
# route_plan_geometry

SPEED_DERATE_FACTOR = D("0.6")


def route_total_length_m(segments):
    total = sum((dec(segment["length_m"]) for segment in segments), D(0))
    return float(rhu(total, 1))


def route_crossing_count(segments):
    return sum(1 for segment in segments if segment["segment_type"] == "CROSSING")


def planned_duration_min(total_length_m, robot):
    effective = dec(robot["max_speed_cm_s"]) * SPEED_DERATE_FACTOR
    return ceil_div(dec(total_length_m), effective)


# --------------------------------------------------------------- calculation 6
# takeover_mandatory


def takeover_mandatory(confidence_pct, zone):
    return dec(confidence_pct) <= dec(zone["takeover_confidence_threshold_pct"])


# --------------------------------------------------------------- calculation 7
# customer_remedy_amount

DECLARED_VALUE_CAP_CENTS = 15000
REMEDY_POLICY = {
    "WEATHER": {"fee": D("1.00"), "declared": D("0.00"), "goodwill": 200},
    "VANDALISM": {"fee": D("1.00"), "declared": D("0.60"), "goodwill": 500},
    "BLOCKED_ROUTE": {"fee": D("0.50"), "declared": D("0.00"), "goodwill": 150},
    "ROBOT_FAULT": {"fee": D("0.35"), "declared": D("0.60"), "goodwill": 250},
    "LATE": {"fee": D("0.25"), "declared": D("0.00"), "goodwill": 150},
}


def customer_remedy_amount(order, remedy_kind):
    if remedy_kind == "REDELIVER":
        return 0
    policy = REMEDY_POLICY[order["exception_reason"]]
    goodwill = policy["goodwill"]
    if remedy_kind == "GOODWILL_CREDIT":
        return int(goodwill)
    fee_basis = order["settled_fee_cents"]
    if fee_basis is None:
        fee_basis = order["quoted_fee_cents"]
    bucket_fee = rhu(dec(fee_basis) * policy["fee"], 0)
    capped = min(D(order["declared_value_cents"]), D(DECLARED_VALUE_CAP_CENTS))
    bucket_declared = rhu(capped * policy["declared"], 0)
    return int(bucket_fee + bucket_declared + D(goodwill))


# --------------------------------------------------------------- calculation 8
# zone_cost_per_delivery

ZONE_SHIFT_MINUTES = 600
OVERHEAD_BASE_CENTS = 40000
OVERHEAD_PER_UTILIZATION_POINT_CENTS = 150
VARIABLE_CENTS_PER_100M = 9
VARIABLE_CENTS_PER_INTERVENTION = 140
UTILIZATION_CEILING_PCT = D("100.0")


def zone_economics(zone):
    zone_id = zone["id"]
    robots = [r for r in db.robots.values() if r["zone_id"] == zone_id]
    robot_ids = set(r["id"] for r in robots)
    terminal = [
        m
        for m in db.missions.values()
        if m["robot_id"] in robot_ids and m["mission_state"] in TERMINAL_MISSION_STATES
    ]

    # step 1
    robot_active_minutes = sum(int(m["active_minutes"]) for m in terminal)
    # step 2
    fleet_capacity_minutes = (
        sum(1 for r in robots if r["duty_state"] != "RETIRED") * ZONE_SHIFT_MINUTES
    )
    # step 3
    if fleet_capacity_minutes == 0:
        utilization = D("0.0")
    else:
        raw = dec(robot_active_minutes) / dec(fleet_capacity_minutes) * D(100)
        if raw > UTILIZATION_CEILING_PCT:
            raw = UTILIZATION_CEILING_PCT
        utilization = rhu(raw, 1)
    # step 4 consumes the rounded utilisation
    allocated_overhead_cents = OVERHEAD_BASE_CENTS + OVERHEAD_PER_UTILIZATION_POINT_CENTS * int(
        floor_dec(utilization)
    )
    # step 5
    total_traveled_m = sum((dec(m["traveled_distance_m"]) for m in terminal), D(0))
    total_interventions = sum(int(m["intervention_count"]) for m in terminal)
    variable_cost_cents = (
        VARIABLE_CENTS_PER_100M * ceil_div(total_traveled_m, 100)
        + VARIABLE_CENTS_PER_INTERVENTION * total_interventions
        + int(zone["remedy_spent_cents"])
    )
    # step 6
    merchant_ids = set(m["id"] for m in db.merchants.values() if m["zone_id"] == zone_id)
    delivered_orders = [
        o
        for o in db.orders.values()
        if o["merchant_id"] in merchant_ids and o["order_state"] in ("DELIVERED", "REFUNDED")
    ]
    delivered_count = len(delivered_orders)
    if delivered_count == 0:
        cost_per_delivery_cents = None
        contribution_per_delivery_cents = None
    else:
        cost_per_delivery_cents = rhu_int(
            dec(allocated_overhead_cents + variable_cost_cents) / dec(delivered_count)
        )
        # step 7
        revenue = sum(
            (dec(o["settled_fee_cents"]) for o in delivered_orders if o["settled_fee_cents"] is not None),
            D(0),
        ) - sum(
            (dec(o["remedy_amount_cents"]) for o in delivered_orders if o["remedy_amount_cents"] is not None),
            D(0),
        )
        contribution_per_delivery_cents = (
            rhu_int(revenue / dec(delivered_count)) - cost_per_delivery_cents
        )
    # step 8
    if fleet_capacity_minutes == 0:
        throughput = D("0.00")
    else:
        throughput = rhu(dec(delivered_count) / (dec(fleet_capacity_minutes) / D(60)), 2)

    return {
        "zone_id": zone_id,
        "robot_active_minutes": robot_active_minutes,
        "fleet_capacity_minutes": fleet_capacity_minutes,
        "utilization_pct": float(utilization),
        "allocated_overhead_cents": allocated_overhead_cents,
        "variable_cost_cents": variable_cost_cents,
        "delivered_count": delivered_count,
        "cost_per_delivery_cents": cost_per_delivery_cents,
        "contribution_per_delivery_cents": contribution_per_delivery_cents,
        "throughput_per_robot_hour": float(throughput),
    }


# --------------------------------------------------------------- calculation 9
# bay_minutes_ledger

TURNAROUND_BUFFER_MINUTES = 15
LEDGER_ACTIVE_STATES = ("HELD", "ACTIVE")


def window_minutes(start_iso, end_iso):
    delta = parse_ts(end_iso) - parse_ts(start_iso)
    return int(delta.total_seconds() // 60)


# -------------------------------------------------------------- calculation 11
# robot_selector

MIN_BATTERY_PCT = D("35.0")
LOW_BATTERY_PCT = D("20.0")
MIN_ROLLING_INDEX = 70
ELIGIBLE_HEALTH_STATES = ("NOMINAL", "DEGRADED")
ELIGIBLE_DUTY_STATE = "AVAILABLE"


def robot_matches_core(robot, zone):
    if robot["duty_state"] != ELIGIBLE_DUTY_STATE:
        return False
    if robot["health_state"] not in ELIGIBLE_HEALTH_STATES:
        return False
    if dec(robot["battery_pct"]) < MIN_BATTERY_PCT:
        return False
    if zone is not None and dec(robot["max_speed_cm_s"]) > dec(zone["ordinance_max_speed_cm_s"]):
        return False
    if int(robot["rolling_autonomy_index"]) < MIN_ROLLING_INDEX:
        return False
    return True


def selector_rank(robot):
    return (
        -int(robot["rolling_autonomy_index"]),
        -float(robot["battery_pct"]),
        robot["created_at"],
        robot["_seq"],
    )


def eligible_robots(zone, payload_liters=None):
    pool = []
    for robot in db.robots.values():
        if robot["zone_id"] != zone["id"]:
            continue
        if not robot_matches_core(robot, zone):
            continue
        if payload_liters is not None and dec(robot["container_capacity_liters"]) < dec(
            payload_liters
        ):
            continue
        pool.append(robot)
    pool.sort(key=selector_rank)
    return pool


# -------------------------------------------------------------- calculation 12
# exception_reason_mapping

CLOSURE_CAUSE_MAP = {
    "WEATHER": "WEATHER",
    "VANDALISM": "VANDALISM",
    "CONSTRUCTION": "BLOCKED_ROUTE",
    "EVENT": "BLOCKED_ROUTE",
}


def abort_reason_to_exception(abort_reason, robot):
    if abort_reason == "ROBOT_QUARANTINED":
        return "VANDALISM" if robot and robot.get("tamper_flag") else "ROBOT_FAULT"
    if abort_reason == "ZONE_REVOKED":
        return "BLOCKED_ROUTE"
    if abort_reason == "DISPATCH_CANCELLED":
        return "ROBOT_FAULT"
    if abort_reason == "UNRECOVERABLE_BLOCKAGE":
        return "BLOCKED_ROUTE"
    return "ROBOT_FAULT"
