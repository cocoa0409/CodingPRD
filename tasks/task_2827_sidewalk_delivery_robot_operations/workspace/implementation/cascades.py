"""Shared cascades and multi-row side effects."""

import calc
from db import bump, create_row, db, now, now_iso, parse_ts, plus_hours

OPEN_MISSION_STATES = ("PLANNED", "LOADED", "EN_ROUTE", "BLOCKED")
OPEN_TAKEOVER_STATES = ("REQUESTED", "ACKNOWLEDGED", "ACTIVE", "ESCALATED")


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def zone_of_robot(robot):
    return db.zones.get(robot["zone_id"]) if robot else None


def zone_of_segment(segment):
    return db.zones.get(segment["zone_id"]) if segment else None


def zone_of_merchant(merchant):
    return db.zones.get(merchant["zone_id"]) if merchant else None


def open_takeover_exists(mission):
    for event in db.interventions.values():
        if event["mission_id"] == mission["id"] and event["takeover_state"] in OPEN_TAKEOVER_STATES:
            return True
    return False


def whole_minutes_between(start_iso, end_iso):
    delta = parse_ts(end_iso) - parse_ts(start_iso)
    return int(delta.total_seconds() // 60)


def whole_seconds_between(start_iso, end_iso):
    delta = parse_ts(end_iso) - parse_ts(start_iso)
    return int(delta.total_seconds())


# ------------------------------------------------------------ merchant ledger


def escrow_on_intake(merchant, amount_cents):
    merchant["escrowed_fee_cents"] += amount_cents
    bump(merchant)


def escrow_to_recognized(merchant, amount_cents):
    merchant["escrowed_fee_cents"] -= amount_cents
    merchant["recognized_fee_cents"] += amount_cents
    bump(merchant)


def escrow_to_released(merchant, amount_cents):
    merchant["escrowed_fee_cents"] -= amount_cents
    merchant["released_fee_cents"] += amount_cents
    bump(merchant)


def released_to_escrow(merchant, amount_cents):
    merchant["released_fee_cents"] -= amount_cents
    merchant["escrowed_fee_cents"] += amount_cents
    bump(merchant)


# --------------------------------------------------------------- bay ledger


def add_bay_minutes(bay, minutes):
    bay["committed_minutes"] += minutes
    bump(bay)
    zone = db.zones.get(bay["zone_id"])
    if zone is not None:
        zone["reserved_bay_minutes"] += minutes
        bump(zone)


def remove_bay_minutes(bay, minutes):
    bay["committed_minutes"] -= minutes
    bump(bay)
    zone = db.zones.get(bay["zone_id"])
    if zone is not None:
        zone["reserved_bay_minutes"] -= minutes
        bump(zone)


def cancel_reservation_row(reservation, target_state):
    reservation["state"] = target_state
    bump(reservation)
    bay = db.bays.get(reservation["bay_id"])
    if bay is not None:
        remove_bay_minutes(bay, reservation["window_minutes"])
    robot = db.robots.get(reservation["robot_id"])
    if robot is not None and robot.get("current_bay_reservation_id") == reservation["id"]:
        robot["current_bay_reservation_id"] = None
        bump(robot)


# ------------------------------------------------------------- order effects


def order_to_exception(order, reason):
    if order is None:
        return
    if order["order_state"] not in ("RECEIVED", "DISPATCHED", "IN_TRANSIT"):
        # A terminal order, and an order already sitting in EXCEPTION, must never
        # move the merchant's money a second time; that would break the fee ledger.
        return
    order["order_state"] = "EXCEPTION"
    order["exception_reason"] = reason
    bump(order)
    merchant = db.merchants.get(order["merchant_id"])
    if merchant is not None:
        escrow_to_released(merchant, order["quoted_fee_cents"])
        merchant["exception_count"] += 1
        bump(merchant)


# ------------------------------------------------------------- route plans


def reject_mission_plans(mission):
    plans = by_created(
        [
            p
            for p in db.plans.values()
            if p["mission_id"] == mission["id"]
            and p["plan_state"] in ("DRAFT", "VALIDATED", "ACTIVE")
        ]
    )
    for plan in plans:
        plan["plan_state"] = "REJECTED"
        plan["rejection_reason"] = "OPERATOR_REJECTED"
        bump(plan)


def supersede_plan(plan, reason, clear_mission_pointer=True):
    plan["plan_state"] = "SUPERSEDED"
    plan["rejection_reason"] = reason
    bump(plan)
    if clear_mission_pointer:
        mission = db.missions.get(plan["mission_id"])
        if mission is not None and mission.get("active_route_plan_id") == plan["id"]:
            mission["active_route_plan_id"] = None
            bump(mission)


# ------------------------------------------------------------ robot effects


def absorb_terminal_mission(robot, mission, park_state):
    """Counter roll-up plus both autonomy recomputations for a terminal mission."""
    if robot is None:
        return
    robot["lifetime_mission_count"] += 1
    robot["lifetime_intervention_count"] += mission["intervention_count"]
    robot["lifetime_escalation_count"] += mission["escalation_count"]
    if mission["intervention_count"] == 0:
        robot["clean_mission_count"] += 1
    robot["rolling_autonomy_index"] = calc.rolling_autonomy_index(robot)
    robot["lifetime_autonomy_index"] = calc.lifetime_autonomy_index(robot)
    if robot["duty_state"] == "ON_MISSION":
        robot["duty_state"] = park_state
        robot["active_mission_id"] = None
        zone = db.zones.get(robot["zone_id"])
        if zone is not None:
            zone["on_mission_robot_count"] -= 1
            if zone["on_mission_robot_count"] < 0:
                zone["on_mission_robot_count"] = 0
            bump(zone)
    bump(robot)


def abort_mission(mission, abort_reason, park_state="AVAILABLE"):
    robot = db.robots.get(mission["robot_id"])
    mission["mission_state"] = "ABORTED"
    mission["abort_reason"] = abort_reason
    mission["completed_at_utc"] = now_iso()
    if mission["departed_at_utc"] is None:
        mission["active_minutes"] = 0
    else:
        mission["active_minutes"] = whole_minutes_between(
            mission["departed_at_utc"], mission["completed_at_utc"]
        )
    bump(mission)
    reject_mission_plans(mission)
    order = db.orders.get(mission["order_id"])
    order_to_exception(order, calc.abort_reason_to_exception(abort_reason, robot))
    absorb_terminal_mission(robot, mission, park_state)


def quarantine_robot(robot, tamper=False):
    """The four link quarantine cascade."""
    robot["health_state"] = "QUARANTINED"
    if tamper:
        robot["tamper_flag"] = True
    bump(robot)
    if robot["duty_state"] != "ON_MISSION":
        return
    mission = db.missions.get(robot.get("active_mission_id") or "")
    if mission is None:
        return
    abort_mission(mission, "ROBOT_QUARANTINED", park_state="MAINTENANCE")
    zone = db.zones.get(robot["zone_id"])
    incident = create_incident_row(
        zone_id=robot["zone_id"],
        robot_id=robot["id"],
        mission_id=mission["id"],
        category="VANDALISM",
        severity="SERIOUS",
        narrative="Automatically filed on robot quarantine cascade.",
        estimated_damage_cents=0,
        filed_by_user_id="SYSTEM",
        zone=zone,
    )
    if zone is not None:
        zone["open_incident_count"] += 1
        bump(zone)
    return incident


def revoke_zone(zone, reason):
    zone["permit_state"] = "REVOKED"
    zone["restriction_reason"] = reason
    robot_ids = set(r["id"] for r in db.robots.values() if r["zone_id"] == zone["id"])
    missions = by_created(
        [
            m
            for m in db.missions.values()
            if m["robot_id"] in robot_ids and m["mission_state"] in OPEN_MISSION_STATES
        ]
    )
    for mission in missions:
        abort_mission(mission, "ZONE_REVOKED")
    bump(zone)


# --------------------------------------------------------- incident creation


def create_incident_row(
    zone_id,
    robot_id,
    mission_id,
    category,
    severity,
    narrative,
    estimated_damage_cents,
    filed_by_user_id,
    zone,
):
    threshold = zone["insurer_notify_threshold_cents"] if zone is not None else 0
    notify = severity == "CRITICAL" or estimated_damage_cents >= threshold
    row = create_row(
        db.incidents,
        {
            "zone_id": zone_id,
            "robot_id": robot_id,
            "mission_id": mission_id,
            "category": category,
            "severity": severity,
            "narrative": narrative,
            "estimated_damage_cents": estimated_damage_cents,
            "report_state": "DRAFT",
            "filed_by_user_id": filed_by_user_id,
            "reviewed_by_user_id": None,
            "municipal_case_ref": None,
            "insurer_claim_ref": None,
            "insurer_notification_required": bool(notify),
            "municipal_due_by_utc": None,
        },
    )
    if severity in ("SERIOUS", "CRITICAL"):
        row["municipal_due_by_utc"] = _plus_72h(row["created_at"])
    return row


def _plus_72h(created_at_iso):
    from db import format_ts

    return format_ts(plus_hours(parse_ts(created_at_iso), 72))


def refresh_zone_budget(zone):
    if zone is None:
        return
    zone["remedy_budget_remaining_cents"] = (
        zone["remedy_budget_cents"] - zone["remedy_spent_cents"]
    )
