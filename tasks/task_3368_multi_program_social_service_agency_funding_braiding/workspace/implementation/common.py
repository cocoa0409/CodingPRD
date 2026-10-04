"""Shared rounding discipline, resource resolution and guardrail helpers."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import ApiError


# --- rounding -------------------------------------------------------------

def _dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half up (a value exactly at the halfway point moves away from zero)."""
    quant = Decimal(1).scaleb(-places)
    return _dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def ratio6(value):
    return float(round_half_up(value, 6))


def pct2(value):
    return float(round_half_up(value, 2))


# --- resolution (priority 3: existence, left to right in path order) ------

def resolve(collection, row_id, error_id, label):
    row = db.get(collection, row_id)
    if row is None:
        raise ApiError(error_id, "%s %r does not resolve." % (label, row_id))
    return row


def resolve_client(row_id):
    return resolve("clients", row_id, "ERR_CLIENT_NOT_FOUND", "Client")


def resolve_program(row_id):
    return resolve("programs", row_id, "ERR_PROGRAM_NOT_FOUND", "Program")


def resolve_grant(row_id):
    return resolve("grants", row_id, "ERR_GRANT_NOT_FOUND", "Grant")


def resolve_funder(row_id):
    return resolve("funders", row_id, "ERR_GRANT_NOT_FOUND", "Funder")


def resolve_enrollment(row_id):
    return resolve("enrollments", row_id, "ERR_ENROLLMENT_NOT_FOUND", "Enrollment")


def resolve_authorization(row_id):
    return resolve(
        "service_authorizations", row_id, "ERR_AUTHORIZATION_NOT_FOUND",
        "ServiceAuthorization",
    )


def resolve_delivery(row_id):
    return resolve("service_deliveries", row_id, "ERR_DELIVERY_NOT_FOUND", "ServiceDelivery")


def resolve_outcome_report(row_id):
    return resolve(
        "outcome_reports", row_id, "ERR_OUTCOME_REPORT_NOT_FOUND", "OutcomeReport",
    )


def resolve_assessment(row_id):
    return resolve(
        "intake_assessments", row_id, "ERR_INVALID_STATE", "IntakeAssessment",
    )


def resolve_screen(row_id):
    return resolve("eligibility_screens", row_id, "ERR_INVALID_STATE", "EligibilityScreen")


# --- graph traversal (a rule reads its parent through the child's own FK) ---

def funder_of_grant(grant):
    return db.get("funders", grant.get("funder_id"))


def program_of_grant(grant):
    return db.get("programs", grant.get("program_id"))


def enrollment_of_authorization(auth):
    return db.get("enrollments", auth.get("enrollment_id"))


def authorization_of_delivery(delivery):
    return db.get("service_authorizations", delivery.get("service_authorization_id"))


# --- public-funding guardrails (§2.8) -------------------------------------

def assert_faith_based_ok(grant, program):
    """Public dollars from a funder that forbids it may not touch a program
    carrying an explicitly religious activity component."""
    funder = funder_of_grant(grant)
    if funder is None:
        return
    if funder.get("allow_faith_based_activity") is False and program is not None \
            and program.get("faith_based_activity_offered") is True:
        raise ApiError(
            "ERR_FAITH_BASED_ACTIVITY_PROHIBITED",
            "Funder %s does not permit public funds to support an explicitly "
            "religious activity component." % funder.get("name"),
        )


def assert_nondiscrimination_ok(grant, program):
    """A program must attest nondiscrimination before it may be screened or
    enrolled under a FEDERAL or STATE funder."""
    if program is None:
        return
    funder = funder_of_grant(grant)
    if funder is None:
        return
    if funder.get("funder_type") in ("FEDERAL", "STATE") \
            and program.get("nondiscrimination_attested") is not True:
        raise ApiError(
            "ERR_NONDISCRIMINATION_VIOLATION",
            "Program %s has not attested nondiscrimination and may not be "
            "screened or enrolled under a %s funder."
            % (program.get("name"), funder.get("funder_type")),
        )


def assert_grant_not_frozen(grant):
    """Priority 4: a grant at posture FROZEN refuses all child writes."""
    if grant is not None and grant.get("status") == "FROZEN":
        raise ApiError(
            "ERR_GRANT_FROZEN",
            "Grant %s is FROZEN and refuses child writes." % grant.get("grant_code"),
        )


def now():
    return clock.now()
