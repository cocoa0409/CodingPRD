"""Complaints, appeals and mutual-recognition obligations (PRD 3.10)."""

from flask import Blueprint

import calc
import domain
import store
from auth import APPLICANT_CONTACT, COMPLAINT_OFFICER, endpoint, owns_body_organization
from envelope import created, single
from errors import ApiError
from validators import body, enum_field, string_field

bp = Blueprint("complaints", __name__)

KINDS = ("COMPLAINT", "APPEAL")
RESOLUTIONS = ("UPHELD", "DISMISSED")
LIVE_SCOPE_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.post("/accreditation/complaints")
@endpoint([APPLICANT_CONTACT, COMPLAINT_OFFICER], owner=owns_body_organization)
def file_case(user_id, role):
    payload = body()
    kind = enum_field(payload, "kind", KINDS)
    organization_id = string_field(payload, "organization_id", 1)
    summary = string_field(payload, "summary", 1, 800)
    filed_by_name = string_field(payload, "filed_by_name", 1, 120)
    application_id = string_field(payload, "application_id", 1, required=False)

    if kind == "APPEAL" and application_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "an APPEAL requires the appealed application_id")
    if kind == "COMPLAINT" and application_id is not None:
        raise ApiError("ERR_INVALID_REQUEST", "a COMPLAINT must not carry an application_id")

    domain.find("organizations", organization_id)
    if application_id is not None:
        domain.find("applications", application_id)

    case = store.insert("complaints", {
        "kind": kind,
        "organization_id": organization_id,
        "application_id": application_id,
        "reviewer_assessor_id": None,
        "summary": summary,
        "filed_by_name": filed_by_name,
        "status": "RECEIVED",
        "resolution_note": None,
        "resolved_on": None,
        "mra_body": None,
        "mra_escalated_on": None,
    })
    return created(store.public(case))


@bp.post("/accreditation/complaints/<complaint_id>/review")
@endpoint([COMPLAINT_OFFICER])
def assign_reviewer(user_id, role, complaint_id):
    payload = body()
    reviewer_assessor_id = string_field(payload, "reviewer_assessor_id", 1)

    case = domain.find("complaints", complaint_id)
    reviewer = domain.find("assessors", reviewer_assessor_id)

    if case["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RECEIVED case may be sent for review")
    if reviewer["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the nominated reviewer is not in QUALIFIED standing")

    verdict = calc.conflict_verdict(reviewer_assessor_id, case["organization_id"],
                                    store.clock_date())
    if verdict == "BLOCKED":
        raise ApiError("ERR_IMPARTIALITY_CONFLICT")

    if case["kind"] == "APPEAL" and case["application_id"]:
        assignment = domain.any_assignment(
            case["application_id"], reviewer_assessor_id,
            statuses=("PROPOSED", "CONFIRMED", "RECUSED"))
        if assignment is not None:
            raise ApiError("ERR_APPEAL_REVIEWER_CONFLICT")
        if domain.voted_on_application(case["application_id"], reviewer_assessor_id):
            raise ApiError("ERR_APPEAL_REVIEWER_CONFLICT")

    case["reviewer_assessor_id"] = reviewer_assessor_id
    case["status"] = "UNDER_REVIEW"
    store.touch(case)
    return single(store.public(case))


@bp.post("/accreditation/complaints/<complaint_id>/resolve")
@endpoint([COMPLAINT_OFFICER])
def resolve_case(user_id, role, complaint_id):
    payload = body()
    outcome = enum_field(payload, "outcome", RESOLUTIONS)
    resolution_note = string_field(payload, "resolution_note", 1, 500)

    case = domain.find("complaints", complaint_id)
    if case["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only an UNDER_REVIEW case may be resolved")

    case["resolution_note"] = resolution_note
    case["resolved_on"] = store.today_iso()
    case["status"] = outcome
    store.touch(case)

    if outcome == "DISMISSED":
        return single(store.public(case))

    organization = store.get("organizations", case["organization_id"])
    if organization is not None:
        organization["upheld_complaint_count"] += 1
        domain.recompute_risk_at_decision(organization, case["application_id"])

    if case["kind"] == "APPEAL" and case["application_id"]:
        application = store.get("applications", case["application_id"])
        if application is not None and application["status"] == "REFUSED":
            application["status"] = "DECISION_PENDING"
            application["decision_round"] += 1
            store.touch(application)
            domain.create_decision_record(application)

    return single(store.public(case))


@bp.post("/accreditation/complaints/<complaint_id>/mra-escalation")
@endpoint([COMPLAINT_OFFICER])
def escalate_to_mra(user_id, role, complaint_id):
    payload = body()
    mra_body = string_field(payload, "mra_body", 1, 120)

    case = domain.find("complaints", complaint_id)
    if case["status"] != "UPHELD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only an UPHELD case may be escalated")
    if case["kind"] != "APPEAL":
        raise ApiError("ERR_MRA_ESCALATION_NOT_ELIGIBLE")

    live_scopes = [s for s in store.ordered(domain.scopes_of(case["organization_id"]))
                   if s["status"] in LIVE_SCOPE_STATUSES]
    if not live_scopes:
        raise ApiError("ERR_MRA_ESCALATION_NOT_ELIGIBLE")

    case["mra_body"] = mra_body
    case["mra_escalated_on"] = store.today_iso()
    case["status"] = "ESCALATED_MRA"
    store.touch(case)

    organization = store.get("organizations", case["organization_id"])
    if organization is not None:
        organization["mra_escalation_count"] += 1
        store.touch(organization)
    for scope in live_scopes:
        store.set_fields(scope, mra_notified=True)

    return single(store.public(case))
