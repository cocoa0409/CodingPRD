"""Neighborhood, SeatAllocation and DeskAssignment routes."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import ALL_ROLES, EMPLOYEE, PEOPLE_MANAGER, WORKPLACE_PROGRAM_OFFICE

bp = Blueprint("space", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)


# --------------------------------------------------------------------------
# neighborhoods
# --------------------------------------------------------------------------
@bp.route("/neighborhoods", methods=["POST"])
def create_neighborhood():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    payload = middleware.body()
    cycle_id = middleware.req_present(payload, "policy_cycle_id")
    cycle = middleware.must_exist("policy_cycle", cycle_id)
    anchor_team_id = middleware.req_present(payload, "anchor_team_id")
    anchor_team = middleware.must_exist("team", anchor_team_id)

    code = middleware.req_string(payload, "neighborhood_code", 1, 24)
    site_code = middleware.req_string(payload, "site_code", 1, 16)
    seat_count = middleware.req_int(payload, "seat_count", 1, 500)
    buffer_seats = middleware.req_int(payload, "buffer_seats", 0)
    desk_from = middleware.req_int(payload, "desk_index_from", 1)
    desk_to = middleware.req_int(payload, "desk_index_to", 1)
    if buffer_seats >= seat_count:
        fail("ERR_INVALID_REQUEST", "buffer_seats must be strictly smaller than seat_count")
    if desk_to < desk_from:
        fail("ERR_INVALID_REQUEST", "desk_index_to must be at least desk_index_from")
    if (desk_to - desk_from + 1) != seat_count:
        fail("ERR_INVALID_REQUEST", "the desk index band width must equal seat_count")

    guards.gate_cycle_not_locked(cycle)

    for existing in db.find("neighborhood", policy_cycle_id=cycle["id"]):
        if existing["neighborhood_code"] == code:
            fail("ERR_DUPLICATE_NEIGHBORHOOD_CODE",
                 "neighborhood_code is already in use on this cycle")

    row = db.insert("neighborhood", {
        "policy_cycle_id": cycle["id"],
        "anchor_team_id": anchor_team["id"],
        "neighborhood_code": code,
        "site_code": site_code,
        "seat_count": seat_count,
        "buffer_seats": buffer_seats,
        "desk_index_from": desk_from,
        "desk_index_to": desk_to,
        "committed_seats": 0,
        "peak_committed_seats": 0,
        "utilization_pct": Decimal("0.00"),
        "allocation_state": "FROZEN" if cycle["posture"] == "LOCKED" else "OPEN",
    })
    return guards.single("neighborhood", row, 201)


@bp.route("/neighborhoods/<neighborhood_id>", methods=["GET"])
def get_neighborhood(neighborhood_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("neighborhood", neighborhood_id)
    return guards.single("neighborhood", row)


@bp.route("/neighborhoods", methods=["GET"])
def list_neighborhoods():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("neighborhood")
    for arg in ("policy_cycle_id", "anchor_team_id", "allocation_state"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("neighborhood", rows,
                        sort_key=lambda n: (n["neighborhood_code"], db.seq_key(n)))


# --------------------------------------------------------------------------
# seat allocations
# --------------------------------------------------------------------------
@bp.route("/seat-allocations", methods=["POST"])
def create_allocation():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    payload = middleware.body()
    neighborhood_id = middleware.req_present(payload, "neighborhood_id")
    neighborhood = middleware.must_exist("neighborhood", neighborhood_id)
    team_id = middleware.req_present(payload, "team_id")
    team = middleware.must_exist("team", team_id)

    allocated_seats = middleware.req_int(payload, "allocated_seats", 1, 500)
    start_label = middleware.req_present(payload, "window_start_week")
    end_label = middleware.req_present(payload, "window_end_week")
    expected_version = middleware.req_int(payload, "expected_neighborhood_version")

    start_index = clock.week_index(start_label) if isinstance(start_label, str) else None
    end_index = clock.week_index(end_label) if isinstance(end_label, str) else None
    if start_index is None or end_index is None or end_index <= start_index:
        fail("ERR_INVALID_INTERVAL", "the seat allocation week window is not a non-empty "
                                    "half-open interval of well-formed ISO week labels")

    guards.occ_check(expected_version, neighborhood, "neighborhood")
    cycle = db.get("policy_cycle", neighborhood["policy_cycle_id"])
    guards.gate_cycle_not_locked(cycle)

    if team["policy_cycle_id"] != neighborhood["policy_cycle_id"]:
        fail("ERR_TEAM_ALLOCATION_MISMATCH",
             "team and neighborhood must belong to the same policy cycle")

    live = [a for a in db.find("seat_allocation", team_id=team["id"])
            if a["status"] != "RELEASED"]
    for index in range(start_index, end_index):
        total = allocated_seats
        for allocation in live:
            other_start = clock.week_index(allocation["window_start_week"])
            other_end = clock.week_index(allocation["window_end_week"])
            if other_start is None or other_end is None:
                continue
            if other_start <= index < other_end:
                total += allocation["allocated_seats"]
        if total > team["entitled_seats"]:
            fail("ERR_SEAT_ENTITLEMENT_EXCEEDED",
                 "the team's entitled_seats would be exceeded in at least one week")

    row = db.insert("seat_allocation", {
        "neighborhood_id": neighborhood["id"],
        "team_id": team["id"],
        "allocated_seats": allocated_seats,
        "window_start_week": start_label,
        "window_end_week": end_label,
        "status": "RESERVED",
        "weeks_in_window": end_index - start_index,
        "line_chargeback_cents": 0,
        "release_reason": None,
    })
    db.touch(neighborhood)
    return guards.single("seat_allocation", row, 201)


@bp.route("/seat-allocations/<allocation_id>/commit", methods=["POST"])
def commit_allocation(allocation_id):
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    allocation = middleware.must_exist("seat_allocation", allocation_id)
    neighborhood = db.get("neighborhood", allocation["neighborhood_id"])
    cycle = db.get("policy_cycle", neighborhood["policy_cycle_id"])
    team = db.get("team", allocation["team_id"])

    guards.gate_cycle_not_locked(cycle)
    if allocation["status"] == "RELEASED":
        fail("ERR_ALLOCATION_TERMINAL", "a RELEASED allocation is terminal")
    if allocation["status"] != "RESERVED":
        fail("ERR_ALLOCATION_NOT_RESERVED", "allocation is not RESERVED")
    if neighborhood["allocation_state"] == "FROZEN":
        fail("ERR_CYCLE_LOCKED", "the neighborhood is FROZEN")

    capacity = neighborhood["seat_count"] - neighborhood["buffer_seats"]
    others = [a for a in db.find("seat_allocation", neighborhood_id=neighborhood["id"],
                                 status="COMMITTED") if a["id"] != allocation["id"]]
    start_index = clock.week_index(allocation["window_start_week"])
    end_index = clock.week_index(allocation["window_end_week"])
    for index in range(start_index, end_index):
        total = allocation["allocated_seats"]
        for other in others:
            other_start = clock.week_index(other["window_start_week"])
            other_end = clock.week_index(other["window_end_week"])
            if other_start <= index < other_end:
                total += other["allocated_seats"]
        if total > capacity:
            fail("ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED",
                 "the neighborhood's usable capacity would be exceeded in at least one week")

    db.apply_changes(allocation, {
        "status": "COMMITTED",
        "line_chargeback_cents": calc.allocation_line_cents(allocation, team),
    })
    recompute.recompute_neighborhood(neighborhood, cycle)
    return guards.single("seat_allocation", allocation)


@bp.route("/seat-allocations/<allocation_id>/release", methods=["POST"])
def release_allocation(allocation_id):
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE,))
    allocation = middleware.must_exist("seat_allocation", allocation_id)
    neighborhood = db.get("neighborhood", allocation["neighborhood_id"])
    cycle = db.get("policy_cycle", neighborhood["policy_cycle_id"])
    payload = middleware.body()
    reason = middleware.req_string(payload, "release_reason", 1, None)

    if allocation["status"] == "RELEASED":
        fail("ERR_ALLOCATION_TERMINAL", "a RELEASED allocation is terminal")

    was_committed = allocation["status"] == "COMMITTED"
    changes = {"status": "RELEASED", "release_reason": reason}
    if was_committed:
        changes["line_chargeback_cents"] = 0
    db.apply_changes(allocation, changes)
    if was_committed:
        assignments = db.find("desk_assignment", seat_allocation_id=allocation["id"])
        assignments.sort(key=lambda a: (a["start_date"], a["desk_index"], db.seq_key(a)))
        for assignment in assignments:
            if assignment["status"] == "ASSIGNED":
                db.apply_changes(assignment, {
                    "status": "VACATED",
                    "vacated_at": clock.now_iso(),
                })
        recompute.recompute_neighborhood(neighborhood, cycle)
    return guards.single("seat_allocation", allocation)


@bp.route("/seat-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("seat_allocation", allocation_id)
    return guards.single("seat_allocation", row)


@bp.route("/seat-allocations", methods=["GET"])
def list_allocations():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("seat_allocation")
    for arg in ("neighborhood_id", "team_id", "status"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("seat_allocation", rows)


# --------------------------------------------------------------------------
# desk assignments
# --------------------------------------------------------------------------
@bp.route("/desk-assignments", methods=["POST"])
def create_assignment():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE, PEOPLE_MANAGER))
    payload = middleware.body()
    allocation_id = middleware.req_present(payload, "seat_allocation_id")
    allocation = middleware.must_exist("seat_allocation", allocation_id)
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)

    desk_index = middleware.req_int(payload, "desk_index", 1)
    start_date = middleware.req_date(payload, "start_date")
    end_date = middleware.req_date(payload, "end_date")
    if end_date < start_date:
        fail("ERR_INVALID_INTERVAL", "end_date must not fall before start_date")

    neighborhood = db.get("neighborhood", allocation["neighborhood_id"])
    cycle = db.get("policy_cycle", neighborhood["policy_cycle_id"])
    guards.gate_cycle_not_locked(cycle)
    guards.gate_cycle_not_locked(recompute.cycle_of_employee(employee))
    guards.gate_employee_active(employee)

    if employee["team_id"] != allocation["team_id"]:
        fail("ERR_TEAM_ALLOCATION_MISMATCH", "employee is not on the allocation's team")
    if not (neighborhood["desk_index_from"] <= desk_index <= neighborhood["desk_index_to"]):
        fail("ERR_TEAM_ALLOCATION_MISMATCH",
             "desk_index falls outside the neighborhood's declared band")

    window_start = clock.week_index(allocation["window_start_week"])
    window_end = clock.week_index(allocation["window_end_week"])
    for label in clock.weeks_touched(start_date, end_date):
        index = clock.week_index(label)
        if not (window_start <= index < window_end):
            fail("ERR_ASSIGNMENT_OUTSIDE_WINDOW",
                 "the occupancy interval reaches outside the allocation's week window")

    if calc.changeover_conflict(neighborhood["id"], desk_index, start_date, end_date):
        fail("ERR_DESK_CHANGEOVER_CONFLICT",
             "the desk is occupied within the one-day sanitation changeover")

    row = db.insert("desk_assignment", {
        "seat_allocation_id": allocation["id"],
        "employee_id": employee["id"],
        "desk_index": desk_index,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "ASSIGNED",
        "assignment_mode": "MANUAL",
        "vacated_at": None,
    })
    return guards.single("desk_assignment", row, 201)


@bp.route("/desk-assignments/auto", methods=["POST"])
def auto_assign():
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE, PEOPLE_MANAGER))
    payload = middleware.body()
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)

    start_date = middleware.req_date(payload, "start_date")
    end_date = middleware.req_date(payload, "end_date")
    if end_date < start_date:
        fail("ERR_INVALID_INTERVAL", "end_date must not fall before start_date")

    guards.gate_cycle_not_locked(recompute.cycle_of_employee(employee))
    guards.gate_employee_active(employee)

    candidates = calc.desk_candidates(employee, start_date, end_date)
    if not candidates:
        fail("ERR_NO_ELIGIBLE_DESK", "no eligible desk is available for the requested dates")
    allocation, _neighborhood, desk_index = candidates[0]

    row = db.insert("desk_assignment", {
        "seat_allocation_id": allocation["id"],
        "employee_id": employee["id"],
        "desk_index": desk_index,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "status": "ASSIGNED",
        "assignment_mode": "AUTO",
        "vacated_at": None,
    })
    return guards.single("desk_assignment", row, 201)


@bp.route("/desk-assignments/<assignment_id>/vacate", methods=["POST"])
def vacate_assignment(assignment_id):
    middleware.authorize((WORKPLACE_PROGRAM_OFFICE, PEOPLE_MANAGER))
    row = middleware.must_exist("desk_assignment", assignment_id)
    if row["status"] != "ASSIGNED":
        fail("ERR_ASSIGNMENT_NOT_ACTIVE", "desk assignment is not ASSIGNED")
    db.apply_changes(row, {"status": "VACATED", "vacated_at": clock.now_iso()})
    return guards.single("desk_assignment", row)


@bp.route("/desk-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("desk_assignment", assignment_id)
    return guards.single("desk_assignment", row)


@bp.route("/desk-assignments", methods=["GET"])
def list_assignments():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("desk_assignment")
    for arg in ("seat_allocation_id", "employee_id", "status"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("desk_assignment", rows,
                        sort_key=lambda a: (a["start_date"], a["desk_index"], db.seq_key(a)))
