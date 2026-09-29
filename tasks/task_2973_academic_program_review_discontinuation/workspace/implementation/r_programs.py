"""Programs, the catalog axis, metric snapshots, cycles, appointments, plans."""

from decimal import Decimal

from flask import Blueprint, request

import cascade
import derive
import envelope
import filters
import serial
import valid
from errors import ApiError
from guards import (CHAIR, COORD, HR, PROVOST, REGISTRAR, begin)
from store import by_created, db, new_row, now, touch

bp = Blueprint("programs", __name__)

DEGREE_LEVELS = ("UNDERGRADUATE", "GRADUATE", "CERTIFICATE")
CATALOG_STATUSES = ("LISTED", "MARKETING_SUPPRESSED", "ADMISSIONS_CLOSED",
                    "CATALOG_WITHDRAWN")
TENURE_STATUSES = ("TENURED", "TENURE_TRACK", "NON_TENURE_TRACK", "ADJUNCT")

CATALOG_EDGES = {
    ("LISTED", "MARKETING_SUPPRESSED"): (
        "ACTIVE", "UNDER_REVIEW", "IMPROVEMENT_MONITORED",
        "CONSOLIDATION_PENDING", "TEACH_OUT_PENDING", "TEACH_OUT_ACTIVE"),
    ("MARKETING_SUPPRESSED", "LISTED"): (
        "ACTIVE", "UNDER_REVIEW", "IMPROVEMENT_MONITORED"),
    ("MARKETING_SUPPRESSED", "ADMISSIONS_CLOSED"): (
        "UNDER_REVIEW", "CONSOLIDATION_PENDING", "TEACH_OUT_PENDING",
        "TEACH_OUT_ACTIVE", "CONSOLIDATED"),
    ("ADMISSIONS_CLOSED", "CATALOG_WITHDRAWN"): ("DISCONTINUED", "CONSOLIDATED"),
}


def catalog_edge_allowed(current, target, lifecycle):
    allowed = CATALOG_EDGES.get((current, target))
    if allowed is None:
        return False
    return lifecycle in allowed


def new_program_row(code, name, degree_level, department_code, capacity):
    row = new_row()
    row.update({
        "code": code,
        "name": name,
        "degree_level": degree_level,
        "department_code": department_code,
        "host_capacity_per_day": capacity,
        "lifecycle_state": "ACTIVE",
        "catalog_status": "LISTED",
        "catalog_status_pre_decision": None,
        "consolidated_into_program_id": None,
        "discontinuation_override": False,
    })
    return row


# --------------------------------------------------------------------------
# POST /provost/academic-programs
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs", methods=["POST"])
def create_program():
    ctx = begin((COORD,))
    body = ctx.require_object_body()
    code = valid.req_str(body, "code", 4, 12, pattern=valid.PROGRAM_CODE_RE)
    name = valid.req_str(body, "name", 1, 200)
    degree_level = valid.req_enum(body, "degree_level", DEGREE_LEVELS)
    department_code = valid.req_str(body, "department_code", 2, 12)
    capacity = valid.opt_int(body, "host_capacity_per_day", 1, 5, default=2)

    for existing in db.programs.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_PROGRAM_CODE")

    row = new_program_row(code, name, degree_level, department_code, capacity)
    db.programs[row["id"]] = row
    return envelope.created(serial.program(row))


@bp.route("/provost/academic-programs", methods=["GET"])
def list_programs():
    begin((COORD, PROVOST, REGISTRAR, HR))
    rows = by_created(db.programs.values())
    rows = filters.apply_string(rows, "lifecycle_state", "lifecycle_state")
    rows = filters.apply_string(rows, "catalog_status", "catalog_status")
    rows = filters.apply_string(rows, "department_code", "department_code")
    rows = filters.apply_string(
        rows, "consolidated_into_program_id", "consolidated_into_program_id")
    band = request.args.get("viability_band")
    if band is not None:
        rows = [r for r in rows if derive.composite_score(r)[1] == band]
    return envelope.paginate(rows, serial.program)


@bp.route("/provost/academic-programs/<pid>", methods=["GET"])
def get_program(pid):
    ctx = begin((COORD, PROVOST, REGISTRAR, HR, CHAIR))
    program = db.programs.get(pid)
    ctx.chair_owner(program)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")
    return envelope.ok(serial.program(program))


# --------------------------------------------------------------------------
# POST /provost/academic-programs/{id}/catalog-status
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs/<pid>/catalog-status", methods=["POST"])
def set_catalog_status(pid):
    ctx = begin((REGISTRAR,))
    program = db.programs.get(pid)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    body = ctx.require_object_body()
    target = valid.req_enum(body, "target_catalog_status", CATALOG_STATUSES)
    valid.opt_str(body, "suppression_note", 1, 2000)

    ctx.not_terminal(program)

    if not catalog_edge_allowed(program["catalog_status"], target,
                                program["lifecycle_state"]):
        raise ApiError("ERR_CATALOG_TRANSITION_INVALID")

    program["catalog_status"] = target
    touch(program)
    return envelope.ok(serial.program(program))


# --------------------------------------------------------------------------
# metric snapshots
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs/<pid>/metric-snapshots", methods=["POST"])
def create_snapshot(pid):
    ctx = begin((COORD,))
    program = db.programs.get(pid)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    body = ctx.require_object_body()
    term_code = valid.req_str(body, "term_code", 4, 10)
    term_index = valid.req_term_index(body, "term_index")
    headcount = valid.req_int(body, "enrollment_headcount", minimum=0)
    credit_hours = valid.req_int(body, "credit_hours", minimum=0)
    direct_cost = valid.req_int(body, "direct_cost_cents", minimum=0)
    completions = valid.req_int(body, "completions_count", minimum=0)
    demand = valid.req_int(body, "market_demand_index", 0, 100)

    ctx.not_terminal(program)

    for existing in derive.snapshots_of(pid):
        if existing["term_index"] == term_index:
            raise ApiError("ERR_DUPLICATE_TERM_SNAPSHOT")

    row = new_row(versioned=False)
    row.update({
        "program_id": pid,
        "term_code": term_code,
        "term_index": term_index,
        "enrollment_headcount": headcount,
        "credit_hours": credit_hours,
        "direct_cost_cents": direct_cost,
        "completions_count": completions,
        "market_demand_index": demand,
    })
    db.snapshots[row["id"]] = row
    touch(program)
    return envelope.created(serial.snapshot(row))


@bp.route("/provost/academic-programs/<pid>/metric-snapshots", methods=["GET"])
def list_snapshots(pid):
    ctx = begin((COORD, PROVOST, CHAIR))
    program = db.programs.get(pid)
    ctx.chair_owner(program)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")
    rows = by_created([s for s in db.snapshots.values()
                       if s["program_id"] == pid])
    rows = filters.apply_int(rows, "term_index", "term_index")
    return envelope.paginate(rows, serial.snapshot)


# --------------------------------------------------------------------------
# review cycles
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs/<pid>/review-cycles", methods=["POST"])
def create_cycle(pid):
    ctx = begin((COORD,))
    program = db.programs.get(pid)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    body = ctx.require_object_body()
    cycle_year = valid.req_int(body, "cycle_year", 2000, 2100)
    due_at = valid.req_instant(body, "self_study_due_at")
    sections = valid.code_array(body, "required_section_codes", 1, 20,
                                allow_empty=False, required=True)

    ctx.not_terminal(program)

    for existing in db.cycles.values():
        if existing["program_id"] == pid and existing["state"] != "CLOSED":
            raise ApiError("ERR_OPEN_CYCLE_EXISTS")

    row = new_row()
    row.update({
        "program_id": pid,
        "cycle_year": cycle_year,
        "state": "SELF_STUDY_OPEN",
        "self_study_due_at": due_at,
        "required_section_codes": sections,
        "addendum_round": 0,
        "response_concurrence": None,
        "response_text": None,
        "disputed_finding_codes": [],
        "response_submitted_at": None,
        "decided_at": None,
    })
    db.cycles[row["id"]] = row

    if program["lifecycle_state"] in ("ACTIVE", "IMPROVEMENT_MONITORED"):
        program["lifecycle_state"] = "UNDER_REVIEW"
    touch(program)
    return envelope.created(serial.cycle(row))


@bp.route("/provost/academic-programs/<pid>/review-cycles", methods=["GET"])
def list_cycles(pid):
    ctx = begin((COORD, PROVOST, CHAIR))
    program = db.programs.get(pid)
    ctx.chair_owner(program)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")
    rows = [c for c in db.cycles.values() if c["program_id"] == pid]
    rows = sorted(rows, key=lambda c: (-c["cycle_year"], c["created_at"],
                                       c["_seq"]))
    rows = filters.apply_string(rows, "state", "state")
    rows = filters.apply_int(rows, "cycle_year", "cycle_year")
    return envelope.paginate(rows, serial.cycle)


# --------------------------------------------------------------------------
# faculty appointments (creation and listing live under the program)
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs/<pid>/faculty-appointments",
          methods=["POST"])
def create_appointment(pid):
    ctx = begin((HR,))
    program = db.programs.get(pid)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    body = ctx.require_object_body()
    faculty_number = valid.req_str(body, "faculty_number", 4, 20)
    tenure_status = valid.req_enum(body, "tenure_status", TENURE_STATUSES)
    fte = valid.req_decimal(body, "fte", Decimal("0"), Decimal("1.00"),
                            low_exclusive=True, places=2)
    salary = valid.req_int(body, "annual_salary_cents", minimum=0)
    for existing in derive.appointments_of(pid):
        if existing["faculty_number"] == faculty_number:
            valid.fail("faculty_number must be unique within the program.")

    ctx.not_terminal(program)

    row = new_row()
    row.update({
        "program_id": pid,
        "faculty_number": faculty_number,
        "tenure_status": tenure_status,
        "fte": fte,
        "annual_salary_cents": salary,
        "state": "ASSIGNED",
        "reassigned_to_department_code": None,
        "notice_days": None,
        "notice_issued_at": None,
        "separated_at": None,
        "reassignment_withdraw_count": 0,
    })
    db.appointments[row["id"]] = row
    touch(program)
    return envelope.created(serial.appointment(row))


@bp.route("/provost/academic-programs/<pid>/faculty-appointments",
          methods=["GET"])
def list_appointments(pid):
    ctx = begin((HR, PROVOST, COORD, CHAIR))
    program = db.programs.get(pid)
    ctx.chair_owner(program)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    water = derive.waterfall(program)
    rows = derive.appointments_of(pid)

    def sort_key(row):
        position = water["positions"].get(row["id"])
        return (1 if position is None else 0,
                position if position is not None else 0,
                row["created_at"], row["_seq"])

    rows = sorted(rows, key=sort_key)
    rows = filters.apply_string(rows, "state", "state")
    rows = filters.apply_string(rows, "tenure_status", "tenure_status")
    return envelope.paginate(rows, serial.appointment)


# --------------------------------------------------------------------------
# POST /provost/academic-programs/{id}/teach-out-plans
# --------------------------------------------------------------------------

@bp.route("/provost/academic-programs/<pid>/teach-out-plans", methods=["POST"])
def create_plan(pid):
    ctx = begin((CHAIR,))
    program = db.programs.get(pid)
    ctx.chair_owner(program)
    ctx.require(program, "ERR_PROGRAM_NOT_FOUND")

    # check 8: body foreign keys resolve
    decision = None
    if ctx.body is not None and ctx.body.get("decision_id") is not None:
        supplied = ctx.body.get("decision_id")
        decision = db.decisions.get(supplied) if isinstance(supplied, str) else None
        if decision is None:
            raise ApiError("ERR_DECISION_NOT_FOUND")

    body = ctx.require_object_body()
    valid.req_str(body, "decision_id", 1, 200)
    last_admit = valid.req_term_index(body, "last_admit_term_index")
    first_teach_out = valid.req_term_index(body, "first_teach_out_term_index")
    final_award = valid.req_term_index(body, "final_award_term_index")
    expected = valid.req_int(body, "expected_program_version")

    parent_cycle = db.cycles.get(decision["cycle_id"])
    if parent_cycle is None or parent_cycle["program_id"] != pid:
        valid.fail("decision_id must name a decision on this program.")
    if decision["outcome"] not in ("CONSOLIDATION", "DISCONTINUATION"):
        valid.fail("decision_id must name a consolidation or discontinuation "
                   "decision.")

    # check 10: optimistic concurrency on the program
    if expected != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION")

    # check 11
    ctx.not_terminal(program)

    # check 12: the decision must be ratified or effectuated
    if decision["state"] not in ("RATIFIED", "EFFECTUATED"):
        raise ApiError("ERR_DECISION_STATE_INVALID")

    # check 30: the horizon
    if not (last_admit < first_teach_out <= final_award
            and final_award >= decision["effective_term_index"]):
        raise ApiError("ERR_TEACH_OUT_HORIZON_INSUFFICIENT")

    # check 46: a live plan cannot be replaced
    existing_plans = derive.plans_of(pid)
    for plan in existing_plans:
        if plan["state"] in ("APPROVED", "IN_EFFECT", "COMPLETED"):
            raise ApiError("ERR_TEACH_OUT_IN_EFFECT")

    row = new_row()
    row.update({
        "program_id": pid,
        "decision_id": decision["id"],
        "last_admit_term_index": last_admit,
        "first_teach_out_term_index": first_teach_out,
        "final_award_term_index": final_award,
        "state": "DRAFT",
        "plan_revision_round": 0,
        "revision_notes": None,
        "approved_at": None,
        "activated_at": None,
        "completed_at": None,
    })
    db.plans[row["id"]] = row

    for plan in by_created(existing_plans):
        if plan["state"] in ("DRAFT", "SUBMITTED"):
            plan["state"] = "SUPERSEDED"
            touch(plan)

    touch(program)
    return envelope.created(serial.plan(row))
