"""Eligibility screening: the two independent state dimensions, the
verification hop, the determination branches and the capacity cascade."""

from datetime import timedelta

import clock
import db
from common import assert_nondiscrimination_ok, resolve_grant, resolve_program
from errors import ApiError
from services import capacity, confidentiality, intake

VERIFICATION_TTL = timedelta(days=180)
DENIAL_ORDER = (
    "CONFIDENTIALITY_BAR",
    "INCOME_OVER_LIMIT",
    "IMMIGRATION_STATUS",
    "RESIDENCY",
    "PROGRAM_AT_CAPACITY",
)
DENIAL_CODES = set(DENIAL_ORDER)


def expire_stale_screens():
    """A VERIFIED screen whose determination is still PENDING expires when the
    logical clock reaches screened_at + 180 days. Dimension 1 stays PENDING."""
    for screen in db.rows("eligibility_screens"):
        if screen.get("verification_state") != "VERIFIED":
            continue
        if screen.get("determination") != "PENDING":
            continue
        screened_at = screen.get("screened_at")
        if screened_at is None:
            continue
        if clock.now() >= screened_at + VERIFICATION_TTL:
            screen["verification_state"] = "EXPIRED"
            db.touch(screen)


def client_of_assessment(assessment):
    return db.get("clients", assessment.get("client_id"))


def create_screen(assessment, payload):
    program = resolve_program(payload.get("program_id"))
    grant = resolve_grant(payload.get("grant_id"))
    client = client_of_assessment(assessment)
    if client is not None:
        confidentiality.assert_allowed(client, program.get("service_domain"))
    assert_nondiscrimination_ok(grant, program)
    income = payload.get("verified_income_cents")
    household = payload.get("household_size_at_screen")
    if income is None or household is None:
        raise ApiError("ERR_BAD_REQUEST", "verified_income_cents and household_size_at_screen are required.")
    return db.create("eligibility_screens", {
        "intake_assessment_id": assessment["id"],
        "program_id": program["id"],
        "grant_id": grant["id"],
        "verified_income_cents": int(income),
        "household_size_at_screen": int(household),
        "determination": "PENDING",
        "denial_reason_code": None,
        "verification_state": "UNVERIFIED",
        "screened_at": clock.now(),
    })


def _verification_hop(screen):
    if screen.get("verification_state") not in ("UNVERIFIED", "EXPIRED"):
        return
    if (screen.get("verified_income_cents") or 0) <= 0:
        raise ApiError(
            "ERR_INVALID_STATE",
            "A screen with no documented income cannot be verified.",
        )
    screen["verification_state"] = "VERIFIED"
    screen["screened_at"] = clock.now()
    db.touch(screen)


def _first_failing_denial(screen, program, client):
    """The recorded reason is the first failing check in the fixed order."""
    if client is not None and not confidentiality.allowed_tier_first(
            client, program.get("service_domain")):
        return "CONFIDENTIALITY_BAR"
    if capacity.capacity_exhausted(program):
        return "PROGRAM_AT_CAPACITY"
    return None


def _capacity_cascade(program):
    """When enrolled_slots reaches capacity, every PENDING screen for that
    program is set INELIGIBLE with denial_reason_code PROGRAM_AT_CAPACITY."""
    if program.get("enrolled_slots", 0) < program.get("capacity_slots", 0):
        return
    for other in db.rows("eligibility_screens"):
        if other.get("program_id") != program["id"]:
            continue
        if other.get("determination") != "PENDING":
            continue
        other["determination"] = "INELIGIBLE"
        other["denial_reason_code"] = "PROGRAM_AT_CAPACITY"
        db.touch(other)


def _grant_eligible(screen, program, assessment, client):
    confidentiality.assert_allowed(client, program.get("service_domain")) \
        if client is not None else None
    if capacity.capacity_exhausted(program):
        raise ApiError(
            "ERR_PROGRAM_CAPACITY_EXCEEDED",
            "Program %s has no available capacity slot." % program.get("name"),
        )
    screen["determination"] = "ELIGIBLE"
    screen["denial_reason_code"] = None
    db.touch(screen)
    db.create("enrollments", {
        "client_id": assessment.get("client_id"),
        "program_id": screen.get("program_id"),
        "grant_id": screen.get("grant_id"),
        "enrolled_at": clock.now(),
        "exited_at": None,
        "exit_reason": None,
        "status": "PENDING",
    })
    capacity.recompute_program(program)
    _capacity_cascade(program)


def _grant_ineligible(screen, program, client, requested_reason):
    screen["determination"] = "INELIGIBLE"
    reason = _first_failing_denial(screen, program, client)
    if reason is None and requested_reason in DENIAL_CODES:
        reason = requested_reason
    screen["denial_reason_code"] = reason
    db.touch(screen)


def determine(screen, payload):
    assessment = db.get("intake_assessments", screen.get("intake_assessment_id"))
    if assessment is None:
        raise ApiError("ERR_INVALID_STATE", "The parent intake assessment does not resolve.")
    requested = payload.get("determination")
    if requested is not None and requested not in ("ELIGIBLE", "INELIGIBLE"):
        raise ApiError("ERR_BAD_REQUEST", "determination must be ELIGIBLE or INELIGIBLE.")

    _verification_hop(screen)
    if requested is None:
        return screen

    if assessment.get("status") != "ROUTED":
        raise ApiError(
            "ERR_INTAKE_NOT_ROUTED",
            "The parent intake assessment is not ROUTED; the screen cannot be determined.",
        )
    if screen.get("determination") != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The screen has already been determined.")
    if screen.get("verification_state") != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", "The screen is not verified.")

    program = db.get("programs", screen.get("program_id"))
    client = db.get("clients", assessment.get("client_id"))
    if requested == "ELIGIBLE":
        _grant_eligible(screen, program, assessment, client)
    else:
        _grant_ineligible(screen, program, client, payload.get("denial_reason_code"))

    intake.evaluate_closure(assessment.get("client_id"))
    return screen
