"""Enrollment lifecycle: direct creation, activation, suspension, exit, denial."""

import clock
import db
from common import (
    assert_faith_based_ok,
    assert_grant_not_frozen,
    assert_nondiscrimination_ok,
)
from errors import ApiError
from services import capacity, confidentiality, intake

EXIT_REASONS = ("COMPLETED", "WITHDRAWN", "TRANSFERRED", "GRANT_TERMINATED", "NONCOMPLIANCE")
PENDING_EXIT_REASONS = ("WITHDRAWN",)
SUSPENDED_EXIT_REASONS = ("WITHDRAWN", "TRANSFERRED", "GRANT_TERMINATED", "NONCOMPLIANCE")


def eligibility_established(client_id, program_id, grant_id):
    for screen in db.rows("eligibility_screens"):
        if screen.get("determination") != "ELIGIBLE":
            continue
        if screen.get("verification_state") != "VERIFIED":
            continue
        if screen.get("program_id") != program_id or screen.get("grant_id") != grant_id:
            continue
        assessment = db.get("intake_assessments", screen.get("intake_assessment_id"))
        if assessment is not None and assessment.get("client_id") == client_id:
            return True
    return False


def create(client, program, grant):
    assert_grant_not_frozen(grant)
    confidentiality.assert_allowed(client, program.get("service_domain"))
    assert_nondiscrimination_ok(grant, program)
    if not eligibility_established(client["id"], program["id"], grant["id"]):
        raise ApiError(
            "ERR_ELIGIBILITY_NOT_ESTABLISHED",
            "No eligibility screen for this client, program and grant carries an "
            "ELIGIBLE determination with VERIFIED documentation.",
        )
    for existing in db.rows("enrollments"):
        if existing.get("client_id") != client["id"]:
            continue
        if existing.get("program_id") != program["id"]:
            continue
        if existing.get("status") in capacity.COUNTING_STATUSES:
            raise ApiError(
                "ERR_CLIENT_ALREADY_ENROLLED",
                "The client already holds an open enrollment for this program.",
            )
    if capacity.capacity_exhausted(program):
        raise ApiError(
            "ERR_PROGRAM_CAPACITY_EXCEEDED",
            "Program %s has no available capacity slot." % program.get("name"),
        )
    enrollment = db.create("enrollments", {
        "client_id": client["id"],
        "program_id": program["id"],
        "grant_id": grant["id"],
        "enrolled_at": clock.now(),
        "exited_at": None,
        "exit_reason": None,
        "status": "PENDING",
    })
    capacity.recompute_program(program)
    return enrollment


def _in_award_period(grant):
    now = clock.now()
    start = grant.get("period_start")
    end = grant.get("period_end")
    if start is None or end is None:
        return False
    return start <= now <= end


def activate(enrollment):
    status = enrollment.get("status")
    if status not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING or SUSPENDED enrollment may be activated.")
    grant = db.get("grants", enrollment.get("grant_id"))
    assert_grant_not_frozen(grant)
    if grant is None or grant.get("status") not in ("OPEN", "THROTTLED"):
        raise ApiError("ERR_INVALID_STATE", "The governing grant does not admit activation.")
    if not _in_award_period(grant):
        raise ApiError("ERR_INVALID_STATE", "The logical clock is outside the grant award period.")
    if status == "PENDING":
        program = db.get("programs", enrollment.get("program_id"))
        if program is None or program.get("status") != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "The program is not ACTIVE.")
    enrollment["status"] = "ACTIVE"
    db.touch(enrollment)
    client = db.get("clients", enrollment.get("client_id"))
    if client is not None:
        capacity.recompute_client(client)
    return enrollment


def _expire_authorizations(enrollment):
    for auth in db.rows("service_authorizations"):
        if auth.get("enrollment_id") != enrollment["id"]:
            continue
        if auth.get("status") == "ACTIVE":
            auth["status"] = "EXPIRED"
            db.touch(auth)


def exit_enrollment(enrollment, reason):
    status = enrollment.get("status")
    if status == "PENDING":
        allowed = PENDING_EXIT_REASONS
    elif status == "ACTIVE":
        allowed = EXIT_REASONS
    elif status == "SUSPENDED":
        allowed = SUSPENDED_EXIT_REASONS
    else:
        raise ApiError("ERR_INVALID_STATE", "This enrollment is in a terminal state.")
    if reason not in allowed:
        raise ApiError(
            "ERR_INVALID_STATE",
            "exit_reason %r is not permitted from status %s." % (reason, status),
        )
    enrollment["status"] = "EXITED"
    enrollment["exited_at"] = clock.now()
    enrollment["exit_reason"] = reason
    db.touch(enrollment)
    program = db.get("programs", enrollment.get("program_id"))
    if program is not None:
        capacity.recompute_program(program)
    if status == "ACTIVE":
        client = db.get("clients", enrollment.get("client_id"))
        if client is not None:
            capacity.recompute_client(client)
    if status in ("ACTIVE", "SUSPENDED"):
        _expire_authorizations(enrollment)
    intake.evaluate_closure(enrollment.get("client_id"))
    return enrollment


def deny(enrollment):
    """System path: the capacity cascade denies the seat the screen created."""
    enrollment["status"] = "DENIED"
    db.touch(enrollment)
    program = db.get("programs", enrollment.get("program_id"))
    if program is not None:
        capacity.recompute_program(program)
    intake.evaluate_closure(enrollment.get("client_id"))
    return enrollment
