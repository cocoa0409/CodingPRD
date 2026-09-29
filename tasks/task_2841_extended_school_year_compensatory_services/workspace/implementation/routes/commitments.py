"""Service commitments and the pinned minute plan (PRD section 3.4)."""
from flask import Blueprint, g, request

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PROGRAM_COORDINATOR,
                  SPED_DIRECTOR, endpoint)
from calcs import esy_service_minutes_plan
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from ledgers import (leave_assignment, recompute_run_seats,
                     recompute_student_ledger)
from resolve import body_ref, path_ref
from serialize import many, public
from store import creation_order, db, new_record, touch
from validate import body, req_enum, req_int, req_str

bp = Blueprint("commitments", __name__)

SERVICE_TYPES = ("SPECIALIZED_INSTRUCTION", "SPEECH", "OT", "PT", "COUNSELING")
STAFFING_RATIOS = ("ONE_TO_ONE", "ONE_TO_THREE", "ONE_TO_SIX", "GROUP_TEN")
COMMITMENT_STATUSES = ("PLANNED", "ASSIGNED", "ACTIVE", "SUSPENDED", "COMPLETED",
                       "TERMINATED")
SEAT_HOLDING = ("PLANNED", "ASSIGNED", "ACTIVE", "SUSPENDED")
READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR, COMPLIANCE_OFFICER)


@bp.post("/esy/service-commitments")
@endpoint((CASE_MANAGER, PROGRAM_COORDINATOR))
def create_commitment():
    data = body()
    # PRD 2.6 fixes the body resolution order: student_id, program_id, then run.
    body_ref(data, "student_id", "student")
    program = body_ref(data, "program_id", "program")
    run = body_ref(data, "transportation_run_id", "run")

    program_id = req_str(data, "program_id", 1, None)
    student_id = req_str(data, "student_id", 1, None)
    service_type = req_enum(data, "service_type", SERVICE_TYPES)
    iep_weekly_minutes = req_int(data, "iep_weekly_minutes", 1, 1500)
    staffing_ratio = req_enum(data, "staffing_ratio", STAFFING_RATIOS)
    run_id = data.get("transportation_run_id")
    if run_id is not None and not isinstance(run_id, str):
        raise ApiError("ERR_INVALID_REQUEST")

    student = db.students[student_id]
    if program["status"] != "PLANNING":
        raise ApiError("ERR_INVALID_STATE")
    if student["esy_eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_STUDENT_NOT_ESY_ELIGIBLE")

    plan = esy_service_minutes_plan(program, iep_weekly_minutes)

    if run is not None:
        seated = sum(1 for c in db.commitments.values()
                     if c["transportation_run_id"] == run["id"]
                     and c["status"] in SEAT_HOLDING)
        if seated + 1 > run["vehicle_capacity_seats"]:
            raise ApiError("ERR_RUN_CAPACITY_EXCEEDED")

    commitment = new_record("ServiceCommitment", {
        "program_id": program_id,
        "student_id": student_id,
        "transportation_run_id": run["id"] if run is not None else None,
        "service_type": service_type,
        "iep_weekly_minutes": iep_weekly_minutes,
        "staffing_ratio": staffing_ratio,
        "planned_total_minutes": plan["planned_total_minutes"],
        "weekly_minutes_committed": plan["weekly_minutes_committed"],
        "daily_minutes": plan["daily_minutes"],
        "delivered_minutes": 0,
        "compensable_owed_minutes": 0,
        "status": "PLANNED",
    })
    db.commitments[commitment["id"]] = commitment
    if run is not None:
        recompute_run_seats(run)
    return created(public(commitment))


@bp.get("/esy/service-commitments")
@endpoint(READ_ROLES)
def list_commitments():
    rows = list(db.commitments.values())
    for key in ("program_id", "student_id", "transportation_run_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, page_meta = paginate(creation_order(rows))
    return ok_list(many(page), page_meta)


@bp.get("/esy/service-commitments/<commitment_id>")
@endpoint(READ_ROLES)
def get_commitment(commitment_id):
    return ok(public(path_ref("commitment", commitment_id)))


@bp.get("/esy/service-commitments/<commitment_id>/provider-assignments")
@endpoint(READ_ROLES)
def list_commitment_assignments(commitment_id):
    path_ref("commitment", commitment_id)
    rows = creation_order([a for a in db.assignments.values()
                           if a["commitment_id"] == commitment_id])
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)


@bp.post("/esy/service-commitments/<commitment_id>/status")
@endpoint((PROGRAM_COORDINATOR, COMPLIANCE_OFFICER))
def set_commitment_status(commitment_id):
    commitment = path_ref("commitment", commitment_id)
    data = body()
    target = req_enum(data, "target_status", COMMITMENT_STATUSES)
    program = db.programs.get(commitment["program_id"])
    student = db.students.get(commitment["student_id"])

    # PRD 3.4: activation and reactivation are ProgramCoordinator acts; only
    # suspension and termination are shared with the ComplianceOfficer.
    if target == "ACTIVE" and g.role != PROGRAM_COORDINATOR:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    if target == "ACTIVE":
        if commitment["status"] not in ("ASSIGNED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        if program is None or program["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        commitment["status"] = "ACTIVE"
        touch(commitment)
    elif target == "SUSPENDED":
        if commitment["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        if student is not None and student["stay_put_active"]:
            raise ApiError("ERR_STAY_PUT_BLOCKED")
        # PRD 3.4: a suspended commitment keeps its transportation seat.
        commitment["status"] = "SUSPENDED"
        touch(commitment)
    elif target == "TERMINATED":
        if commitment["status"] not in ("PLANNED", "ASSIGNED", "ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        if student is not None and student["stay_put_active"]:
            raise ApiError("ERR_STAY_PUT_BLOCKED")
        for assignment in creation_order(
                [a for a in db.assignments.values()
                 if a["commitment_id"] == commitment["id"] and a["status"] == "ACTIVE"]):
            leave_assignment(assignment, "RELEASED", "COMMITMENT_TERMINATED")
        commitment["status"] = "TERMINATED"
        touch(commitment)
        run = db.runs.get(commitment.get("transportation_run_id") or "")
        if run is not None:
            recompute_run_seats(run)
        if student is not None:
            recompute_student_ledger(student)
    else:
        raise ApiError("ERR_INVALID_STATE")

    return ok(public(commitment))
