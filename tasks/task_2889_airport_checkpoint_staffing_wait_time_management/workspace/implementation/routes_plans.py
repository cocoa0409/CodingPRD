"""Staffing plans and lane assignments."""

from flask import Blueprint

import calc
import cascade
import consts
import derive
import envelope
import req
import serial
import store
from errors import bad_request, fail
from util import day_bounds, parse_date

bp = Blueprint("plans", __name__)

PLAN_SPEC = [
    {
        "name": "checkpoint_id",
        "kind": "string",
        "required": True,
        "fk": "checkpoint",
        "collection": "checkpoints",
    },
    {"name": "operational_date", "kind": "date", "required": True},
    {"name": "expected_checkpoint_version", "kind": "integer", "required": True, "min": 0},
]


@bp.post("/staffing-plans")
def create_plan():
    _role, user_id = req.actor(["StaffingPlanner"])
    values = req.parse_body(PLAN_SPEC)
    parents = req.resolve_fks(values, PLAN_SPEC)
    checkpoint = parents["checkpoint_id"]
    if values["expected_checkpoint_version"] != checkpoint["version"]:
        fail(
            "ERR_STALE_CHECKPOINT_VERSION",
            "expected_checkpoint_version %s does not match %s"
            % (values["expected_checkpoint_version"], checkpoint["version"]),
        )
    row = store.base()
    row.update(
        {
            "checkpoint_id": checkpoint["id"],
            "superseded_by_staffing_plan_id": None,
            "operational_date": values["operational_date"],
            "state": "DRAFT",
            "revision_number": 1,
            "prepared_by_user_id": user_id,
            "approved_by_user_id": None,
            "rejection_reason_code": None,
            "submitted_at_utc": None,
            "approved_at_utc": None,
            "activated_at_utc": None,
            "closed_at_utc": None,
            "planned_regular_minutes": None,
            "planned_overtime_minutes": None,
            "base_cost_cents": None,
            "overtime_cost_cents": None,
            "detail_cost_cents": None,
            "subtotal_cents": None,
            "admin_fee_rate": None,
            "admin_fee_cents": None,
            "total_cost_cents": None,
        }
    )
    store.add("staffing_plans", row)
    cascade.bump_checkpoint(checkpoint)
    return envelope.obj(serial.staffing_plan(row), 201)


@bp.get("/staffing-plans/<staffing_plan_id>")
def read_plan(staffing_plan_id):
    req.actor(req.READ_ROLES)
    row = req.load("staffing_plan", staffing_plan_id)
    return envelope.obj(serial.staffing_plan(row))


@bp.get("/staffing-plans")
def list_plans():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    state = req.query_enum("state", consts.PLAN_STATES)
    rows = req.filter_rows(
        store.rows("staffing_plans"),
        {
            "checkpoint_id": req.query_value("checkpoint_id"),
            "superseded_by_staffing_plan_id": req.query_value("superseded_by_staffing_plan_id"),
            "state": state,
        },
    )
    raw_date = req.query_value("operational_date")
    if raw_date is not None:
        parsed = parse_date(raw_date)
        if parsed is None:
            bad_request("operational_date must be a YYYY-MM-DD date")
        rows = [p for p in rows if p["operational_date"] == parsed]
    rows.sort(key=lambda p: (p["operational_date"], p["created_at"], p["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.staffing_plan, page), limit, offset, total)


def _plan_checkpoint(plan):
    return store.get("checkpoints", plan["checkpoint_id"])


def _guard_suspended(checkpoint):
    if checkpoint is not None and derive.posture(checkpoint) == "SUSPENDED":
        fail("ERR_CHECKPOINT_SUSPENDED", "the checkpoint is suspended")


def _live_plan_assignments(plan_id):
    return [
        a
        for a in store.rows("lane_assignments")
        if a["staffing_plan_id"] == plan_id and a["assignment_state"] != "CANCELLED"
    ]


def _check_coverage(plan):
    assignments = _live_plan_assignments(plan["id"])
    band_ids = []
    for assignment in assignments:
        if assignment["time_band_id"] not in band_ids:
            band_ids.append(assignment["time_band_id"])
    bands = [store.get("time_bands", bid) for bid in band_ids]
    bands = [b for b in bands if b is not None]
    bands.sort(key=lambda b: (b["band_start_utc"], b["_seq"]))
    for band in bands:
        if band["forecast_pax_count"] is None or band["required_standard_lanes"] is None:
            fail("ERR_BAND_NOT_FORECAST", "time band %s has not been forecast" % band["id"])
    for band in bands:
        standard = set()
        expedited = set()
        for assignment in assignments:
            if assignment["time_band_id"] != band["id"]:
                continue
            lane = store.get("lanes", assignment["lane_id"])
            if lane is None:
                continue
            if lane["lane_type"] == "STANDARD":
                standard.add(lane["id"])
            else:
                expedited.add(lane["id"])
        need_standard = max(
            band["required_standard_lanes"], consts.MIN_OPEN_LANES["STANDARD"]
        )
        if len(standard) < need_standard:
            fail(
                "ERR_MIN_LANES_NOT_MET",
                "band %s staffs %d standard lanes but needs %d"
                % (band["id"], len(standard), need_standard),
            )
        if len(expedited) < band["required_expedited_lanes"]:
            fail(
                "ERR_MIN_LANES_NOT_MET",
                "band %s staffs %d expedited lanes but needs %d"
                % (band["id"], len(expedited), band["required_expedited_lanes"]),
            )


def _check_plan_overtime(cost):
    for entry in cost["officer_breakdown"]:
        officer = store.get("officers", entry["officer_id"])
        if officer is None:
            continue
        if entry["overtime_minutes"] > officer["weekly_overtime_minutes_cap"]:
            fail(
                "ERR_OVERTIME_CAP_EXCEEDED",
                "officer %s exceeds the weekly overtime cap" % officer["badge_number"],
            )


def _check_cost_cap(plan, cost):
    checkpoint = _plan_checkpoint(plan)
    if checkpoint is None:
        return
    if cost["total_cost_cents"] > checkpoint["plan_cost_cap_cents"]:
        fail(
            "ERR_PLAN_COST_CAP_EXCEEDED",
            "total cost %d exceeds the cap %d"
            % (cost["total_cost_cents"], checkpoint["plan_cost_cap_cents"]),
        )


@bp.post("/staffing-plans/<staffing_plan_id>/submit")
def submit_plan(staffing_plan_id):
    req.actor(["StaffingPlanner"])
    plan = req.load("staffing_plan", staffing_plan_id)
    _guard_suspended(_plan_checkpoint(plan))
    if plan["state"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s plan cannot be submitted" % plan["state"])
    if not _live_plan_assignments(plan["id"]):
        fail("ERR_INVALID_STATE_TRANSITION", "the plan has no live lane assignments")
    _check_coverage(plan)
    cost = calc.staffing_plan_cost(plan)
    _check_plan_overtime(cost)
    _check_cost_cap(plan, cost)
    plan["state"] = "SUBMITTED"
    plan["submitted_at_utc"] = store.now()
    for field in calc.COST_FIELDS:
        plan[field] = cost[field]
    store.touch(plan)
    return envelope.obj(serial.staffing_plan(plan))


DECISION_SPEC = [
    {"name": "decision", "kind": "enum", "required": True, "values": ("APPROVE", "REJECT")},
    {
        "name": "rejection_reason_code",
        "kind": "enum",
        "values": consts.REJECTION_REASON_CODES,
    },
]


@bp.post("/staffing-plans/<staffing_plan_id>/decision")
def decide_plan(staffing_plan_id):
    _role, user_id = req.actor(["DutyManager"])
    values = req.parse_body(DECISION_SPEC)
    decision = values["decision"]
    if decision == "REJECT" and "rejection_reason_code" not in values:
        bad_request("rejection_reason_code is required when rejecting")
    if decision == "APPROVE" and "rejection_reason_code" in values:
        bad_request("rejection_reason_code is forbidden when approving")
    plan = req.load("staffing_plan", staffing_plan_id)
    if user_id == plan["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the preparer may not decide their own plan")
    checkpoint = _plan_checkpoint(plan)
    _guard_suspended(checkpoint)
    if plan["state"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s plan cannot be decided" % plan["state"])
    if decision == "REJECT":
        plan["state"] = "REJECTED"
        plan["rejection_reason_code"] = values["rejection_reason_code"]
        store.touch(plan)
        return envelope.obj(serial.staffing_plan(plan))
    cost = calc.staffing_plan_cost(plan)
    _check_plan_overtime(cost)
    _check_cost_cap(plan, cost)
    plan["state"] = "APPROVED"
    plan["approved_by_user_id"] = user_id
    plan["approved_at_utc"] = store.now()
    for field in calc.COST_FIELDS:
        plan[field] = cost[field]
    store.touch(plan)
    cascade.supersede_other_plans(plan)
    cascade.bump_checkpoint(checkpoint)
    if checkpoint is not None:
        derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.staffing_plan(plan))


@bp.post("/staffing-plans/<staffing_plan_id>/revise")
def revise_plan(staffing_plan_id):
    req.actor(["StaffingPlanner"])
    plan = req.load("staffing_plan", staffing_plan_id)
    if plan["state"] != "REJECTED":
        fail("ERR_INVALID_STATE_TRANSITION", "a %s plan cannot be revised" % plan["state"])
    plan["state"] = "DRAFT"
    plan["revision_number"] += 1
    plan["rejection_reason_code"] = None
    plan["submitted_at_utc"] = None
    for field in calc.COST_FIELDS:
        plan[field] = None
    store.touch(plan)
    return envelope.obj(serial.staffing_plan(plan))


LIFECYCLE_SPEC = [
    {"name": "action", "kind": "enum", "required": True, "values": ("ACTIVATE", "CLOSE")}
]


@bp.post("/staffing-plans/<staffing_plan_id>/lifecycle")
def plan_lifecycle(staffing_plan_id):
    req.actor(["CheckpointManager"])
    values = req.parse_body(LIFECYCLE_SPEC)
    plan = req.load("staffing_plan", staffing_plan_id)
    _guard_suspended(_plan_checkpoint(plan))
    action = values["action"]
    if action == "ACTIVATE":
        if plan["state"] != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION", "a %s plan cannot be activated" % plan["state"])
        if plan["operational_date"] != store.now().date():
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "the plan's operational_date is not the current logical date",
            )
        plan["state"] = "ACTIVATED"
        plan["activated_at_utc"] = store.now()
    else:
        if plan["state"] != "ACTIVATED":
            fail("ERR_INVALID_STATE_TRANSITION", "a %s plan cannot be closed" % plan["state"])
        plan["state"] = "CLOSED"
        plan["closed_at_utc"] = store.now()
        cascade.retire_plan_assignments(plan)
    store.touch(plan)
    return envelope.obj(serial.staffing_plan(plan))


@bp.get("/staffing-plans/<staffing_plan_id>/cost-summary")
def plan_cost_summary(staffing_plan_id):
    req.actor(["PlatformAdmin", "CheckpointManager", "StaffingPlanner", "DutyManager"])
    plan = req.load("staffing_plan", staffing_plan_id)
    cost = calc.staffing_plan_cost(plan)
    payload = {"staffing_plan_id": plan["id"]}
    for field in calc.COST_FIELDS:
        payload[field] = cost[field]
    payload["officer_breakdown"] = cost["officer_breakdown"]
    return envelope.obj(store.render(payload))


# ---------------------------------------------------------------------------
# LaneAssignment
# ---------------------------------------------------------------------------
ASSIGNMENT_SPEC = [
    {
        "name": "staffing_plan_id",
        "kind": "string",
        "required": True,
        "fk": "staffing_plan",
        "collection": "staffing_plans",
    },
    {"name": "lane_id", "kind": "string", "required": True, "fk": "lane", "collection": "lanes"},
    {
        "name": "officer_id",
        "kind": "string",
        "required": True,
        "fk": "officer",
        "collection": "officers",
    },
    {
        "name": "time_band_id",
        "kind": "string",
        "required": True,
        "fk": "time_band",
        "collection": "time_bands",
    },
]

LIVE_STATES = ("SCHEDULED", "CHECKED_IN")


def _band_of(assignment):
    return store.get("time_bands", assignment["time_band_id"])


def _check_certified(officer, lane):
    needed = "EXPEDITED_LANE" if lane["lane_type"] == "EXPEDITED" else "STANDARD_LANE"
    certs = officer["certifications"]
    if needed not in certs:
        fail("ERR_OFFICER_NOT_CERTIFIED", "the officer lacks %s" % needed)
    if derive.lane_has_advanced_imaging(lane) and "ADVANCED_IMAGING" not in certs:
        fail("ERR_OFFICER_NOT_CERTIFIED", "the officer lacks ADVANCED_IMAGING")


def _officer_live_bands(officer_id, exclude_id=None):
    out = []
    for row in store.rows("lane_assignments"):
        if row["officer_id"] != officer_id or row["assignment_state"] not in LIVE_STATES:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        band = _band_of(row)
        if band is not None:
            out.append((band["band_start_utc"], band["band_end_utc"]))
    return out


def _check_double_booked(officer, band):
    start, end = band["band_start_utc"], band["band_end_utc"]
    for other_start, other_end in _officer_live_bands(officer["id"]):
        if other_start < end and start < other_end:
            fail("ERR_OFFICER_DOUBLE_BOOKED", "the officer already works an overlapping band")


def _check_rest_buffer(officer, band):
    intervals = _officer_live_bands(officer["id"])
    intervals.append((band["band_start_utc"], band["band_end_utc"]))
    intervals.sort()
    run_start, run_end = intervals[0]
    runs = []
    for start, end in intervals[1:]:
        if start <= run_end:
            run_end = max(run_end, end)
        else:
            runs.append((run_start, run_end))
            run_start, run_end = start, end
    runs.append((run_start, run_end))
    for start, end in runs:
        if start <= band["band_start_utc"] and band["band_end_utc"] <= end:
            if (end - start).total_seconds() / 60 > consts.MAX_CONSECUTIVE_ON_POSITION_MINUTES:
                fail(
                    "ERR_OFFICER_REST_BUFFER_REQUIRED",
                    "the band extends the on-position run beyond %d minutes without rest"
                    % consts.MAX_CONSECUTIVE_ON_POSITION_MINUTES,
                )


def _check_lane_capacity(lane, band):
    intervals = [(band["band_start_utc"], band["band_end_utc"])]
    for row in store.rows("lane_assignments"):
        if row["lane_id"] != lane["id"] or row["assignment_state"] not in LIVE_STATES:
            continue
        other = _band_of(row)
        if other is not None:
            intervals.append((other["band_start_utc"], other["band_end_utc"]))
    points = set()
    for start, end in intervals:
        points.add(start)
        points.add(end)
    for point in points:
        overlapping = len([1 for s, e in intervals if s <= point <= e])
        if overlapping > lane["max_concurrent_officers"]:
            fail(
                "ERR_LANE_POSITION_CAPACITY_EXCEEDED",
                "the lane already hosts %d contending assignments" % lane["max_concurrent_officers"],
            )


def _check_overtime(officer, extra_minutes=0):
    ledger = calc.officer_duty_ledger(
        officer, "FORWARD_LOOKING_PLANNED", extra_minutes=extra_minutes
    )
    if ledger["overtime_minutes"] > officer["weekly_overtime_minutes_cap"]:
        fail(
            "ERR_OVERTIME_CAP_EXCEEDED",
            "the officer's overtime %d exceeds the cap %d"
            % (ledger["overtime_minutes"], officer["weekly_overtime_minutes_cap"]),
        )


@bp.post("/lane-assignments")
def create_assignment():
    req.actor(["StaffingPlanner"])
    values = req.parse_body(ASSIGNMENT_SPEC)
    parents = req.resolve_fks(values, ASSIGNMENT_SPEC)
    plan = parents["staffing_plan_id"]
    lane = parents["lane_id"]
    officer = parents["officer_id"]
    band = parents["time_band_id"]
    checkpoint = _plan_checkpoint(plan)
    _guard_suspended(checkpoint)
    if officer["duty_status"] == "SEPARATED":
        fail("ERR_INVALID_STATE_TRANSITION", "a SEPARATED officer cannot be assigned")
    if lane["lane_state"] == "DECOMMISSIONED":
        fail("ERR_INVALID_STATE_TRANSITION", "a DECOMMISSIONED lane cannot be staffed")
    _check_certified(officer, lane)
    if lane["checkpoint_id"] != plan["checkpoint_id"]:
        fail("ERR_LANE_CHECKPOINT_MISMATCH", "the lane belongs to another checkpoint")
    if band["checkpoint_id"] != plan["checkpoint_id"]:
        fail("ERR_TIME_BAND_CHECKPOINT_MISMATCH", "the time band belongs to another checkpoint")
    day_start, day_end = day_bounds(plan["operational_date"])
    if band["band_start_utc"] < day_start or band["band_end_utc"] > day_end:
        fail(
            "ERR_BAND_OUTSIDE_OPERATIONAL_DATE",
            "the band is not inside the plan's operational date",
        )
    _check_double_booked(officer, band)
    _check_rest_buffer(officer, band)
    _check_lane_capacity(lane, band)
    planned = int((band["band_end_utc"] - band["band_start_utc"]).total_seconds() // 60)
    _check_overtime(officer, extra_minutes=planned)
    row = store.base()
    row.update(
        {
            "staffing_plan_id": plan["id"],
            "lane_id": lane["id"],
            "officer_id": officer["id"],
            "time_band_id": band["id"],
            "assignment_state": "SCHEDULED",
            "break_state": "NOT_DUE",
            "checked_in_at_utc": None,
            "released_at_utc": None,
            "break_baseline_utc": None,
            "break_started_at_utc": None,
            "break_ended_at_utc": None,
            "break_minutes_taken": 0,
            "planned_minutes": planned,
        }
    )
    store.add("lane_assignments", row)
    derive.refresh_officer(officer)
    calc.apply_plan_cost(plan)
    return envelope.obj(serial.lane_assignment(row), 201)


@bp.get("/lane-assignments/<lane_assignment_id>")
def read_assignment(lane_assignment_id):
    req.actor(req.READ_ROLES)
    row = req.load("lane_assignment", lane_assignment_id)
    return envelope.obj(serial.lane_assignment(row))


@bp.get("/lane-assignments")
def list_assignments():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    filters = {
        "staffing_plan_id": req.query_value("staffing_plan_id"),
        "lane_id": req.query_value("lane_id"),
        "officer_id": req.query_value("officer_id"),
        "time_band_id": req.query_value("time_band_id"),
        "assignment_state": req.query_enum("assignment_state", consts.ASSIGNMENT_STATES),
        "break_state": req.query_enum("break_state", consts.BREAK_STATES),
    }
    derive.evaluate_all_breaks()
    rows = req.filter_rows(store.rows("lane_assignments"), filters)
    rows.sort(
        key=lambda a: (
            0 if a["checked_in_at_utc"] is not None else 1,
            a["checked_in_at_utc"] or a["created_at"],
            a["created_at"],
            a["_seq"],
        )
    )
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.lane_assignment, page), limit, offset, total)


DUTY_SPEC = [
    {
        "name": "action",
        "kind": "enum",
        "required": True,
        "values": ("CHECK_IN", "RELEASE", "CANCEL"),
    }
]

BREAK_SPEC = [
    {"name": "action", "kind": "enum", "required": True, "values": ("START", "END")}
]


def _require_owner(role, user_id, assignment):
    if role not in consts.OFFICER_BACKED_ROLES:
        return
    if assignment["officer_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the assignment belongs to another officer")


def _check_calibration(lane):
    now = store.now()
    for unit in derive.required_units(lane):
        if unit["calibration_due_utc"] < now:
            fail(
                "ERR_CALIBRATION_OVERDUE",
                "unit %s calibration has lapsed" % unit["equipment_type"],
            )


@bp.post("/lane-assignments/<lane_assignment_id>/duty")
def assignment_duty(lane_assignment_id):
    role, user_id = req.actor(["DutyManager", "ScreeningOfficer", "SupervisoryOfficer"])
    values = req.parse_body(DUTY_SPEC)
    assignment = req.load("lane_assignment", lane_assignment_id)
    derive.evaluate_break_due(assignment)
    action = values["action"]
    if not (action == "RELEASE" and role == "SupervisoryOfficer"):
        _require_owner(role, user_id, assignment)
    plan = store.get("staffing_plans", assignment["staffing_plan_id"])
    lane = store.get("lanes", assignment["lane_id"])
    officer = store.get("officers", assignment["officer_id"])
    checkpoint = _plan_checkpoint(plan) if plan is not None else None
    _guard_suspended(checkpoint)
    state = assignment["assignment_state"]
    if action == "CHECK_IN":
        if state != "SCHEDULED":
            fail("ERR_INVALID_STATE_TRANSITION", "a %s assignment cannot check in" % state)
        if officer is not None and officer["duty_status"] == "SEPARATED":
            fail("ERR_INVALID_STATE_TRANSITION", "a SEPARATED officer cannot check in")
        if plan is None or plan["state"] != "ACTIVATED":
            fail("ERR_PLAN_NOT_ACTIVATED", "the owning plan is not ACTIVATED")
        if lane is None or lane["lane_state"] != "OPEN":
            fail("ERR_LANE_NOT_OPEN", "the assignment's lane is not OPEN")
        _check_calibration(lane)
        if officer is not None:
            _check_overtime(officer)
        now = store.now()
        assignment["assignment_state"] = "CHECKED_IN"
        assignment["checked_in_at_utc"] = now
        assignment["break_baseline_utc"] = now
        store.touch(assignment)
        derive.evaluate_break_due(assignment)
        if officer is not None:
            if officer["duty_status"] == "OFF_DUTY":
                officer["duty_status"] = "ON_DUTY"
                cascade.bump_officer(officer)
            derive.refresh_officer(officer)
    elif action == "RELEASE":
        if state != "CHECKED_IN":
            fail("ERR_INVALID_STATE_TRANSITION", "a %s assignment cannot be released" % state)
        if assignment["break_state"] == "ON_BREAK":
            fail("ERR_INVALID_STATE_TRANSITION", "end the break before releasing")
        cascade.release_assignment(assignment)
        if officer is not None:
            derive.refresh_officer(officer)
        if plan is not None:
            calc.apply_plan_cost(plan)
    else:
        if state != "SCHEDULED":
            fail("ERR_INVALID_STATE_TRANSITION", "a %s assignment cannot be cancelled" % state)
        cascade.cancel_assignment(assignment)
        if officer is not None:
            derive.refresh_officer(officer)
        if plan is not None:
            calc.apply_plan_cost(plan)
    return envelope.obj(serial.lane_assignment(assignment))


@bp.post("/lane-assignments/<lane_assignment_id>/break")
def assignment_break(lane_assignment_id):
    role, user_id = req.actor(["ScreeningOfficer", "SupervisoryOfficer"])
    values = req.parse_body(BREAK_SPEC)
    assignment = req.load("lane_assignment", lane_assignment_id)
    derive.evaluate_break_due(assignment)
    _require_owner(role, user_id, assignment)
    officer = store.get("officers", assignment["officer_id"])
    if values["action"] == "START":
        if assignment["assignment_state"] != "CHECKED_IN":
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "a %s assignment cannot start a break" % assignment["assignment_state"],
            )
        if assignment["break_state"] != "DUE":
            fail("ERR_BREAK_NOT_DUE", "the break is not due")
        assignment["break_state"] = "ON_BREAK"
        assignment["break_started_at_utc"] = store.now()
        store.touch(assignment)
        if officer is not None and officer["duty_status"] == "ON_DUTY":
            officer["duty_status"] = "ON_BREAK"
            cascade.bump_officer(officer)
    else:
        if assignment["break_state"] != "ON_BREAK":
            fail("ERR_BREAK_NOT_DUE", "the assignment is not on break")
        cascade.end_break(assignment)
        store.touch(assignment)
        derive.evaluate_break_due(assignment)
    return envelope.obj(serial.lane_assignment(assignment))
