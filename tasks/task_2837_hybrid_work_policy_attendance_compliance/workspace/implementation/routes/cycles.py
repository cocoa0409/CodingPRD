"""Logical clock, PolicyCycle and Team routes."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import middleware
import recompute
import response
from errors import fail
from middleware import (ALL_ROLES, HR_BUSINESS_PARTNER, WORKPLACE_PROGRAM_OFFICE)

bp = Blueprint("cycles", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != middleware.EMPLOYEE)

POSTURES = ("OPEN", "RECALIBRATING", "LOCKED")
POSTURE_TRANSITIONS = {
    "OPEN": ("RECALIBRATING", "LOCKED"),
    "RECALIBRATING": ("OPEN", "LOCKED"),
    "LOCKED": (),
}
WEEKDAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI")
TEAM_CODE_PATTERN = r"^[A-Z0-9-]+$"


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    payload = middleware.body()
    raw = middleware.req_present(payload, "current_utc")
    parsed = clock.parse_instant(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant")
    clock.set_now(parsed)
    return response.object_response({"current_utc": clock.format_instant(parsed)})


# --------------------------------------------------------------------------
# policy cycles
# --------------------------------------------------------------------------
@bp.route("/policy-cycles", methods=["POST"])
def create_policy_cycle():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    payload = middleware.body()
    cycle_label = middleware.req_string(payload, "cycle_label", 1, 40)
    effective_from = middleware.req_date(payload, "effective_from")
    effective_to = middleware.req_date(payload, "effective_to")
    if effective_to <= effective_from:
        fail("ERR_INVALID_REQUEST", "effective_to must fall strictly after effective_from")
    days_floor = middleware.req_int(payload, "days_in_office_floor", 0, 5)
    badge_weight = middleware.req_decimal(payload, "badge_weight", 0, 1)
    network_weight = middleware.req_decimal(payload, "network_weight", 0, 1)
    if badge_weight + network_weight != Decimal("1.00"):
        fail("ERR_INVALID_REQUEST", "badge_weight and network_weight must sum to 1.00")
    target = middleware.req_decimal(payload, "collaboration_target_score", 0, 100)
    threshold = middleware.req_decimal(payload, "equity_variance_threshold_pct", 0, 100)

    for existing in db.all_rows("policy_cycle"):
        if existing["cycle_label"] == cycle_label:
            fail("ERR_DUPLICATE_CYCLE_LABEL", "cycle_label is already in use")

    row = db.insert("policy_cycle", {
        "cycle_label": cycle_label,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat(),
        "posture": "OPEN",
        "days_in_office_floor": days_floor,
        "badge_weight": badge_weight,
        "network_weight": network_weight,
        "collaboration_target_score": target,
        "equity_variance_threshold_pct": threshold,
        "enrolled_team_count": 0,
        "aggregate_compliance_rate": Decimal("0.00"),
        "formal_action_total": 0,
    })
    return guards.single("policy_cycle", row, 201)


@bp.route("/policy-cycles/<cycle_id>", methods=["GET"])
def get_policy_cycle(cycle_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("policy_cycle", cycle_id)
    return guards.single("policy_cycle", row)


@bp.route("/policy-cycles", methods=["GET"])
def list_policy_cycles():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("policy_cycle")
    posture = middleware.filter_arg("posture")
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    return guards.paged("policy_cycle", rows, reverse=True)


@bp.route("/policy-cycles/<cycle_id>/posture", methods=["POST"])
def set_posture(cycle_id):
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    cycle = middleware.must_exist("policy_cycle", cycle_id)
    payload = middleware.body()
    target = middleware.req_enum(payload, "target_posture", POSTURES)
    middleware.opt_string(payload, "note", 1, None)
    if target not in POSTURE_TRANSITIONS[cycle["posture"]]:
        fail("ERR_INVALID_POSTURE_TRANSITION",
             "cannot move posture from %s to %s" % (cycle["posture"], target))

    db.apply_changes(cycle, {"posture": target})
    if target == "LOCKED":
        _lock_cascade(cycle)
    return guards.single("policy_cycle", cycle)


def _lock_cascade(cycle):
    teams = db.find("team", policy_cycle_id=cycle["id"])
    teams.sort(key=lambda t: (t["team_code"], db.seq_key(t)))
    for team in teams:
        employees = db.find("employee", team_id=team["id"])
        employees.sort(key=lambda e: (e["employee_number"], db.seq_key(e)))
        for employee in employees:
            weeks = db.find("attendance_week", employee_id=employee["id"])
            weeks.sort(key=lambda w: (w["week_start_date"], db.seq_key(w)))
            for week in weeks:
                if week["status"] == "FINALIZED":
                    db.apply_changes(week, {"status": "LOCKED"})
    zones = db.find("neighborhood", policy_cycle_id=cycle["id"])
    zones.sort(key=lambda n: (n["neighborhood_code"], db.seq_key(n)))
    for zone in zones:
        recompute.recompute_neighborhood(zone, cycle)


# --------------------------------------------------------------------------
# teams
# --------------------------------------------------------------------------
@bp.route("/teams", methods=["POST"])
def create_team():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    payload = middleware.body()
    cycle_id = middleware.req_present(payload, "policy_cycle_id")
    cycle = middleware.must_exist("policy_cycle", cycle_id)

    team_code = middleware.req_string(payload, "team_code", 1, 24, TEAM_CODE_PATTERN)
    expected_days = middleware.req_int(payload, "expected_days_in_office_per_week", 0, 5)
    core_days = middleware.req_string_list(payload, "core_collaboration_days",
                                           WEEKDAY_NAMES, 0, 5)
    headcount = middleware.req_int(payload, "headcount_planned", 1, 5000)
    corroboration = middleware.opt_bool(payload, "signal_corroboration_required", False)
    if expected_days < cycle["days_in_office_floor"]:
        fail("ERR_INVALID_REQUEST",
             "expected_days_in_office_per_week must be at least the cycle days_in_office_floor")

    guards.gate_cycle_not_locked(cycle)

    for existing in db.find("team", policy_cycle_id=cycle["id"]):
        if existing["team_code"] == team_code:
            fail("ERR_DUPLICATE_TEAM_CODE", "team_code is already in use on this cycle")

    entitlement = calc.team_seat_entitlement(headcount, expected_days)
    row = db.insert("team", dict({
        "policy_cycle_id": cycle["id"],
        "team_code": team_code,
        "expected_days_in_office_per_week": expected_days,
        "core_collaboration_days": core_days,
        "headcount_planned": headcount,
        "signal_corroboration_required": corroboration,
        "escalated_headcount": 0,
        "formal_action_count": 0,
    }, **entitlement))
    recompute.recompute_cycle_rollups(cycle)
    return guards.single("team", row, 201)


@bp.route("/teams/<team_id>", methods=["GET"])
def get_team(team_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("team", team_id)
    return guards.single("team", row)


@bp.route("/teams", methods=["GET"])
def list_teams():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("team")
    cycle_id = middleware.filter_arg("policy_cycle_id")
    if cycle_id is not None:
        rows = [r for r in rows if r["policy_cycle_id"] == cycle_id]
    return guards.paged("team", rows, sort_key=lambda t: (t["team_code"], db.seq_key(t)))
