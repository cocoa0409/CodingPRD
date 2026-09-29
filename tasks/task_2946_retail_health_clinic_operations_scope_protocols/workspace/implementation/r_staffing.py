"""Routes: staffing assignments, cancellation cascade and float coverage."""

from flask import Blueprint

import calc
import engine
import serial
from auth import (
    ROLE_CLINIC_ADMIN,
    ROLE_CLINICIAN,
    ROLE_PHYSICIAN,
    authenticate,
)
from common import (
    collection,
    get_assignment,
    get_clinic,
    get_clinician,
    get_physician,
    state_rule_or_404,
)
from envelope import object_response
from errors import (
    ERR_CLINICIAN_DOUBLE_BOOKED,
    ERR_CLINICIAN_NOT_LICENSED_IN_STATE,
    ERR_COVERAGE_ALREADY_EXISTS,
    ERR_INVALID_TIME_RANGE,
    ERR_NO_FLOAT_COVERAGE_AVAILABLE,
    ERR_PHYSICIAN_NOT_LICENSED_IN_STATE,
    ERR_SCOPE_HOLD_ACTIVE,
    ERR_STAFFING_ASSIGNMENT_INVALID_STATE,
    ERR_STALE_CLINIC_VERSION,
    ERR_SUPERVISION_CAPACITY_EXCEEDED,
    ERR_SUPERVISION_REQUIRED,
    raise_error,
)
from shapes import (
    json_body,
    present,
    query_enum,
    query_string,
    read_enum,
    read_instant,
    read_int,
    read_string,
    reject_unknown,
)
from store import db, new_row, ordered, touch

bp = Blueprint("staffing", __name__)

ROLE_KINDS = ("PRIMARY", "FLOAT")
ASSIGNMENT_STATUSES = ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")
_LIVE = ("SCHEDULED", "ACTIVE")


def _physician_licensed(physician, clinic):
    if physician["status"] != "ACTIVE":
        return False
    return clinic["state_code"] in physician["licensed_state_codes"]


def _double_booked(clinician_id, starts_at, ends_at, ignore_id=None):
    for row in ordered(db.assignments.values()):
        if row["clinician_id"] != clinician_id:
            continue
        if row["status"] not in _LIVE:
            continue
        if ignore_id is not None and row["id"] == ignore_id:
            continue
        if calc.overlaps(row["starts_at"], row["ends_at"], starts_at, ends_at):
            return True
    return False


def _capacity_would_break(physician, state_rule, clinician_id):
    """A clinician already counted under this physician never trips the cap."""
    counted = set()
    for row in db.assignments.values():
        if row["pinned_supervising_physician_id"] != physician["id"]:
            continue
        if row["status"] not in _LIVE:
            continue
        counted.add(row["clinician_id"])
    if clinician_id in counted:
        return False
    if state_rule is None:
        cap = physician["max_supervised_clinicians"]
    else:
        cap = calc.effective_supervision_cap(physician, state_rule)
    return len(counted) >= cap


def _create_assignment(
    clinic,
    clinician,
    physician_id,
    role_kind,
    starts_at,
    ends_at,
    covers_assignment_id,
):
    row = new_row()
    row.update({
        "clinic_id": clinic["id"],
        "clinician_id": clinician["id"],
        "covers_assignment_id": covers_assignment_id,
        "pinned_supervising_physician_id": physician_id,
        "role_kind": role_kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    engine.activate_if_due(row)
    db.assignments[row["id"]] = row

    engine.refresh_clinic(clinic)
    engine.recompute_physician(physician_id)
    engine.recompute_clinician(clinician["id"])
    return row


# ---------------------------------------------------------------------------
# POST /staffing-assignments
# ---------------------------------------------------------------------------

@bp.route("/staffing-assignments", methods=["POST"])
def create_assignment():
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "clinic_id",
        "clinician_id",
        "role_kind",
        "starts_at",
        "ends_at",
        "pinned_supervising_physician_id",
    })
    clinic_id = read_string(body, "clinic_id")
    clinician_id = read_string(body, "clinician_id")
    role_kind = read_enum(body, "role_kind", ROLE_KINDS)
    starts_at = read_instant(body, "starts_at")
    ends_at = read_instant(body, "ends_at")
    pinned_id = read_string(
        body, "pinned_supervising_physician_id", required=False
    )

    # rung 7 - body references, in declaration order
    clinic = get_clinic(clinic_id)
    clinician = get_clinician(clinician_id)
    if pinned_id is not None:
        physician = get_physician(pinned_id)
    else:
        physician = get_physician(clinician["supervising_physician_id"])

    # rung 8 - state rule presence
    state_rule = state_rule_or_404(clinic["state_code"])

    # rung 13 - scope hold
    if clinician["scope_hold"]:
        raise_error(
            ERR_SCOPE_HOLD_ACTIVE,
            "Clinician %s is on scope hold." % clinician["id"],
        )

    # rung 20 - clinician licensure
    if clinician["license_state_code"] != clinic["state_code"]:
        raise_error(ERR_CLINICIAN_NOT_LICENSED_IN_STATE)

    # rung 21 - physician licensure
    if not _physician_licensed(physician, clinic):
        raise_error(ERR_PHYSICIAN_NOT_LICENSED_IN_STATE)

    # rung 22 - supervision requirement
    if state_rule["collaborating_physician_required"]:
        if pinned_id is None or pinned_id != clinician["supervising_physician_id"]:
            raise_error(ERR_SUPERVISION_REQUIRED)

    # rung 28 - double booking
    if _double_booked(clinician["id"], starts_at, ends_at):
        raise_error(ERR_CLINICIAN_DOUBLE_BOOKED)

    # rung 29 - interval sanity
    if not starts_at < ends_at:
        raise_error(
            ERR_INVALID_TIME_RANGE,
            "Field 'starts_at' must fall strictly before 'ends_at'.",
        )

    # rung 30 - supervision capacity
    if _capacity_would_break(physician, state_rule, clinician["id"]):
        raise_error(ERR_SUPERVISION_CAPACITY_EXCEEDED)

    row = _create_assignment(
        clinic,
        clinician,
        physician["id"],
        role_kind,
        starts_at,
        ends_at,
        None,
    )
    return object_response(serial.assignment(row), 201)


# ---------------------------------------------------------------------------
# POST /staffing-assignments/{assignmentId}/cancel
# ---------------------------------------------------------------------------

@bp.route("/staffing-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=False)
    reject_unknown(body, {"cancel_reason"})
    cancel_reason = read_string(body, "cancel_reason", required=False)

    row = get_assignment(assignment_id)
    if row["status"] not in _LIVE:
        raise_error(
            ERR_STAFFING_ASSIGNMENT_INVALID_STATE,
            "Assignment %s is %s and cannot be cancelled."
            % (row["id"], row["status"]),
        )

    row["status"] = "CANCELLED"
    row["cancel_reason"] = cancel_reason
    touch(row)

    engine.refresh_clinic(db.clinics.get(row["clinic_id"]))
    engine.recompute_physician(row["pinned_supervising_physician_id"])
    engine.recompute_clinician(row["clinician_id"])
    return object_response(serial.assignment(row), 200)


# ---------------------------------------------------------------------------
# POST /clinics/{clinicId}/float-coverages
# ---------------------------------------------------------------------------

@bp.route("/clinics/<clinic_id>/float-coverages", methods=["POST"])
def create_float_coverage(clinic_id):
    authenticate([ROLE_CLINIC_ADMIN])
    body = json_body(required=True)
    reject_unknown(body, {
        "covers_assignment_id",
        "expected_clinic_version",
        "pinned_supervising_physician_id",
    })
    covers_id = read_string(body, "covers_assignment_id")
    expected_version = read_int(body, "expected_clinic_version", minimum=0)
    pinned_id = read_string(
        body, "pinned_supervising_physician_id", required=False
    )

    # rung 6 - path resolution
    clinic = get_clinic(clinic_id)

    # rung 7 - body references
    covered = get_assignment(covers_id)
    supplied_physician = get_physician(pinned_id) if pinned_id is not None else None

    # rung 11 - version pinning
    if expected_version != clinic["version"]:
        raise_error(
            ERR_STALE_CLINIC_VERSION,
            "Clinic %s is at version %d." % (clinic["id"], clinic["version"]),
        )

    # rung 34 - coverage uniqueness
    if covered["status"] != "CANCELLED":
        raise_error(
            ERR_COVERAGE_ALREADY_EXISTS,
            "Assignment %s is not CANCELLED." % covered["id"],
        )
    for row in db.assignments.values():
        if row["covers_assignment_id"] == covered["id"] and row["role_kind"] == "FLOAT":
            raise_error(
                ERR_COVERAGE_ALREADY_EXISTS,
                "Assignment %s is already covered." % covered["id"],
            )

    winner = calc.float_coverage_selection(clinic, covered)
    if winner is None:
        raise_error(ERR_NO_FLOAT_COVERAGE_AVAILABLE)

    if supplied_physician is not None:
        physician = supplied_physician
    else:
        physician = get_physician(winner["supervising_physician_id"])

    state_rule = calc.state_rule_for(clinic["state_code"])

    # rung 30 - supervision capacity on the selected clinician
    if _capacity_would_break(physician, state_rule, winner["id"]):
        raise_error(ERR_SUPERVISION_CAPACITY_EXCEEDED)

    row = _create_assignment(
        clinic,
        winner,
        physician["id"],
        "FLOAT",
        covered["starts_at"],
        covered["ends_at"],
        covered["id"],
    )
    return object_response(serial.assignment(row), 201)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.route("/staffing-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    row = get_assignment(assignment_id)
    return object_response(serial.assignment(row), 200)


@bp.route("/staffing-assignments", methods=["GET"])
def list_assignments():
    authenticate([ROLE_CLINIC_ADMIN, ROLE_CLINICIAN, ROLE_PHYSICIAN])
    clinic_id = query_string("clinic_id")
    clinician_id = query_string("clinician_id")
    covers_assignment_id = query_string("covers_assignment_id")
    pinned_id = query_string("pinned_supervising_physician_id")
    role_kind = query_enum("role_kind", ROLE_KINDS)
    status = query_enum("status", ASSIGNMENT_STATUSES)
    return collection(db.assignments, serial.assignment, [
        (clinic_id, lambda row, v: row["clinic_id"] == v),
        (clinician_id, lambda row, v: row["clinician_id"] == v),
        (covers_assignment_id, lambda row, v: row["covers_assignment_id"] == v),
        (pinned_id, lambda row, v: row["pinned_supervising_physician_id"] == v),
        (role_kind, lambda row, v: row["role_kind"] == v),
        (status, lambda row, v: row["status"] == v),
    ])
