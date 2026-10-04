"""Intake assessment lifecycle: submission, routing, return and closure."""

import db
from errors import ApiError

RETURN_REASONS = ("INCOMPLETE_INCOME", "MISSING_DOCUMENT", "WRONG_DOMAIN")


def screens_for(assessment):
    return [
        row for row in db.rows("eligibility_screens")
        if row.get("intake_assessment_id") == assessment["id"]
    ]


def submit(assessment):
    """DRAFT -> SUBMITTED, and the path back from RETURNED to SUBMITTED."""
    status = assessment.get("status")
    if status not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or RETURNED assessment may be submitted.")
    if not assessment.get("presenting_needs"):
        raise ApiError("ERR_INVALID_STATE", "presenting_needs must carry at least one element.")
    if not assessment.get("requested_domains"):
        raise ApiError("ERR_INVALID_STATE", "requested_domains must carry at least one element.")
    assessment["status"] = "SUBMITTED"
    assessment["return_reason_code"] = None
    db.touch(assessment)
    return assessment


def route(assessment):
    if assessment.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED assessment may be routed.")
    screens = screens_for(assessment)
    if not any(s.get("verification_state") == "VERIFIED" for s in screens):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Routing requires at least one verified eligibility screen.",
        )
    assessment["status"] = "ROUTED"
    if screens and all(s.get("determination") == "INELIGIBLE" for s in screens):
        assessment["routing_outcome"] = "NO_ELIGIBLE_PROGRAM"
    else:
        assessment["routing_outcome"] = "ROUTED"
    db.touch(assessment)
    return assessment


def return_to_specialist(assessment, reason):
    if assessment.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED assessment may be returned.")
    if reason not in RETURN_REASONS:
        raise ApiError(
            "ERR_INVALID_STATE",
            "return_reason_code must be one of INCOMPLETE_INCOME, MISSING_DOCUMENT, WRONG_DOMAIN.",
        )
    assessment["status"] = "RETURNED"
    assessment["return_reason_code"] = reason
    db.touch(assessment)
    for screen in screens_for(assessment):
        screen["verification_state"] = "EXPIRED"
        if screen.get("determination") == "ELIGIBLE":
            screen["determination"] = "PENDING"
        db.touch(screen)
    return assessment


def evaluate_closure(client_id):
    """Evaluated after every enrollment exit and every screen determination
    write. A ROUTED assessment closes once every screen is determined and every
    enrollment opened since the assessment date has reached EXITED or DENIED."""
    for assessment in db.rows("intake_assessments"):
        if assessment.get("client_id") != client_id:
            continue
        if assessment.get("status") != "ROUTED":
            continue
        screens = screens_for(assessment)
        if not all(s.get("determination") in ("ELIGIBLE", "INELIGIBLE") for s in screens):
            continue
        assessment_date = assessment.get("assessment_date")
        relevant = [
            row for row in db.rows("enrollments")
            if row.get("client_id") == client_id
            and (assessment_date is None or row.get("enrolled_at") is None
                 or row.get("enrolled_at") >= assessment_date)
        ]
        if not all(row.get("status") in ("EXITED", "DENIED") for row in relevant):
            continue
        assessment["status"] = "CLOSED"
        client_enrollments = [
            row for row in db.rows("enrollments") if row.get("client_id") == client_id
        ]
        if all(row.get("status") == "DENIED" for row in client_enrollments):
            assessment["routing_outcome"] = "WITHDRAWN"
        db.touch(assessment)
