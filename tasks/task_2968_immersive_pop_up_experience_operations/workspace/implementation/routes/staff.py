"""StaffMember — certifications, the two readiness variants and the staffing
ladder (PRD §3.4)."""

from flask import Blueprint, request

from db import db, new_row, public, touch
from errors import ApiError
from middleware import EP, SO, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body

bp = Blueprint("staff", __name__)

STAFF_ROLES = ("PERFORMER", "AMBASSADOR", "TECHNICIAN")
CERTIFICATIONS = ("SCRIPTED_INTERACTION", "SENSORY_DEESCALATION", "ADA_ASSIST",
                  "EVACUATION_MARSHAL", "RIGGING", "ELECTRICAL")
STAFF_DECISIONS = ("CLEAR", "SUSPEND", "REINSTATE", "RELEASE")
STAFF_RUN_STATUSES = ("PLANNED", "OPEN", "EXTENDED")
TRAINABLE = ("CANDIDATE", "TRAINING")
RELEASABLE = ("CANDIDATE", "TRAINING", "CLEARED", "SUSPENDED")
INCIDENT_MAX = 20


@bp.post("/staff-members")
@roles(EP)
def enrol_member():
    body = Body(require_body=True)
    run_id = body.reference("run_id")
    full_name = body.string("full_name", min_len=1, max_len=80)
    staff_role = body.enum("staff_role", STAFF_ROLES)
    certifications = body.enum_array("certifications", CERTIFICATIONS,
                                     required=False, default=[])
    incidents = body.integer("incident_count", required=False, default=0,
                             minimum=0, maximum=INCIDENT_MAX)

    # rung 5 — body foreign key
    run_row = derive.run(run_id)
    # rung 9 — a closing or closed run takes on nobody
    if run_row["run_status"] not in STAFF_RUN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")

    row = new_row()
    row.update({
        "run_id": run_row["id"],
        "full_name": full_name,
        "staff_role": staff_role,
        "certifications": certifications,
        "incident_count": incidents,
        "training_score": 0,
        "completed_rehearsal_count": 0,
        "scheduled_rehearsal_count": 0,
        # PRD §3.4 lands every derived figure at zero on enrolment; the first
        # training record is what derives cert_coverage_pct and both variants.
        "cert_coverage_pct": 0.00,
        "readiness_score_preflight": 0.00,
        "readiness_score_audit": 0.00,
        "status": "CANDIDATE",
    })
    db.staff[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/staff-members/<staff_id>")
@roles(EP, SO)
def read_member(staff_id):
    return object_response(public(derive.staff(staff_id)))


@bp.get("/staff-members")
@roles(EP, SO)
def list_members():
    rows = list(db.staff.values())
    for field in ("run_id", "staff_role", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/staff-members/<staff_id>/training-records")
@roles(EP)
def record_training(staff_id):
    member = derive.staff(staff_id)
    body = Body(require_body=True)
    score = body.integer("training_score", minimum=0, maximum=100)
    completed = body.integer("completed_rehearsal_count", required=False,
                             default=0, minimum=0, maximum=50)
    scheduled = body.integer("scheduled_rehearsal_count", required=False,
                             default=0, minimum=0, maximum=50)
    incident_delta = body.integer("incident_delta", required=False, default=0,
                                  minimum=0, maximum=INCIDENT_MAX)

    # rung 8 — own state
    if member["status"] not in TRAINABLE:
        raise ApiError("ERR_STAFF_INVALID_STATE")
    # rung 9 — cross-entity state
    run_row = derive.run(member["run_id"])
    if run_row["run_status"] not in STAFF_RUN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")

    # a bad day never erases a good one; rehearsals accumulate
    member["training_score"] = max(member["training_score"], score)
    member["completed_rehearsal_count"] += completed
    member["scheduled_rehearsal_count"] += scheduled
    member["incident_count"] = min(INCIDENT_MAX,
                                   member["incident_count"] + incident_delta)
    member["cert_coverage_pct"] = float(
        calc.cert_coverage_pct(member["staff_role"], member["certifications"]))
    derive.refresh_readiness(member)
    member["status"] = "TRAINING"
    touch(member)
    return object_response(public(member))


def _check_readiness_gates(member):
    """The clearing gate reads the audit variant only."""
    if calc.dec(member["readiness_score_audit"]) < calc.READINESS_CLEAR_MIN:
        raise ApiError("ERR_STAFF_READINESS_BELOW_MIN")
    if member["incident_count"] > calc.INCIDENT_CLEAR_MAX:
        raise ApiError("ERR_STAFF_INCIDENTS_ABOVE_MAX")


@bp.post("/staff-members/<staff_id>/status-decisions")
@roles(EP, SO)
def staff_decision(staff_id):
    member = derive.staff(staff_id)
    body = Body(require_body=True)
    decision = body.enum("decision", STAFF_DECISIONS)
    body.string("note", required=False, default=None, min_len=1, max_len=500)
    run_row = derive.run(member["run_id"])

    if decision == "CLEAR":
        if member["status"] != "TRAINING":
            raise ApiError("ERR_STAFF_INVALID_STATE")
        _check_readiness_gates(member)
        member["status"] = "CLEARED"

    elif decision == "REINSTATE":
        if member["status"] != "SUSPENDED":
            raise ApiError("ERR_STAFF_INVALID_STATE")
        # incidents charged during the suspension can keep the gate shut
        _check_readiness_gates(member)
        member["status"] = "CLEARED"

    elif decision == "SUSPEND":
        if member["status"] != "CLEARED":
            raise ApiError("ERR_STAFF_INVALID_STATE")
        member["status"] = "SUSPENDED"

    else:  # RELEASE — terminal
        if member["status"] not in RELEASABLE:
            raise ApiError("ERR_STAFF_INVALID_STATE")
        member["status"] = "RELEASED"

    touch(member)
    if decision in ("SUSPEND", "RELEASE"):
        derive.cancel_scheduled_shifts(member)
    # every staffing move can open or shut the run's craft gate
    derive.rederive_clearance(run_row)
    return object_response(public(member))
