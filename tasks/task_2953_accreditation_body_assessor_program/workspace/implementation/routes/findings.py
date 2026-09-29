"""Findings, corrective action, effectiveness and escalation (PRD 3.7)."""

from flask import Blueprint

import calc
import domain
import store
from auth import (APPLICANT_CONTACT, ASSESSMENT_MANAGER, LEAD_ASSESSOR,
                  TECHNICAL_EXPERT, endpoint, owns_finding)
from envelope import created, single
from errors import ApiError
from validators import body, enum_field, int_field, string_field

bp = Blueprint("findings", __name__)

CLASSIFICATIONS = ("CRITICAL", "MAJOR", "MINOR", "OBSERVATION")
REVIEW_OUTCOMES = ("ACCEPT", "REJECT")
VERIFY_OUTCOMES = ("PASS", "FAIL")
BLOCKING_CLASSIFICATIONS = ("CRITICAL", "MAJOR", "MINOR")
ESCALABLE_CLASSIFICATIONS = ("CRITICAL", "MAJOR")


@bp.post("/accreditation/applications/<application_id>/nonconformities")
@endpoint([LEAD_ASSESSOR, TECHNICAL_EXPERT])
def raise_finding(user_id, role, application_id):
    payload = body()
    clause_ref = string_field(payload, "clause_ref", 1, 40)
    classification = enum_field(payload, "classification", CLASSIFICATIONS)
    statement = string_field(payload, "statement", 1, 800)

    application = domain.find("applications", application_id)
    if application["suspension_blocked"] or application["status"] not in domain.FINDING_STATUSES:
        raise ApiError("ERR_APPLICATION_STATE_INVALID", "this cycle does not permit findings")
    if domain.confirmed_assignment(application_id, user_id) is None:
        raise ApiError("ERR_NOT_ASSIGNED_TEAM_MEMBER")

    raised_on = store.clock_date()
    due_on = calc.nonconformity_due_on(classification, raised_on, domain.pinned(application))
    finding = store.insert("nonconformities", {
        "application_id": application_id,
        "raised_by_assessor_id": user_id,
        "clause_ref": clause_ref,
        "classification": classification,
        "statement": statement,
        "raised_on": store.iso_date(raised_on),
        "due_on": store.iso_date(due_on) if due_on else None,
        "status": "OPEN",
        "response_round": 0,
        "root_cause": None,
        "action_plan": None,
        "response_submitted_on": None,
        "reviewed_by_assessor_id": None,
        "review_note": None,
        "verified_by_assessor_id": None,
        "verified_evidence_count": 0,
        "effectiveness_outcome": None,
        "closed_on": None,
        "reopen_count": 0,
        "escalated_on": None,
    })

    application["nc_total_count"] += 1
    if classification == "OBSERVATION":
        application["nc_observation_count"] += 1
    else:
        application["nc_blocking_open_count"] += 1
    store.touch(application)

    return created(store.public(finding))


@bp.post("/accreditation/nonconformities/<nonconformity_id>/responses")
@endpoint([APPLICANT_CONTACT], owner=owns_finding)
def submit_response(user_id, role, nonconformity_id):
    payload = body()
    expected_version = int_field(payload, "expected_nonconformity_version", 0, None)
    root_cause = string_field(payload, "root_cause", 1, 500)
    action_plan = string_field(payload, "action_plan", 1, 800)

    finding = domain.find("nonconformities", nonconformity_id)
    if expected_version != finding["version"]:
        raise ApiError("ERR_STALE_NONCONFORMITY_VERSION")
    if finding["status"] != "OPEN" or finding["classification"] == "OBSERVATION":
        raise ApiError("ERR_NONCONFORMITY_STATE_INVALID",
                       "this finding does not accept a corrective-action response")

    application = store.get("applications", finding["application_id"])
    if application["suspension_blocked"] or application["status"] != "NC_OPEN":
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "the cycle must be in NC_OPEN to accept a response")

    from validators import parse_date

    today = store.clock_date()
    if finding["due_on"] and today > parse_date(finding["due_on"], "due_on"):
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    finding["response_round"] += 1
    finding["root_cause"] = root_cause
    finding["action_plan"] = action_plan
    finding["response_submitted_on"] = store.iso_date(today)
    finding["status"] = "RESPONSE_SUBMITTED"
    store.touch(finding)
    return single(store.public(finding))


@bp.post("/accreditation/nonconformities/<nonconformity_id>/review")
@endpoint([LEAD_ASSESSOR])
def review_response(user_id, role, nonconformity_id):
    payload = body()
    outcome = enum_field(payload, "outcome", REVIEW_OUTCOMES)
    review_note = string_field(payload, "review_note", 1, 500)

    finding = domain.find("nonconformities", nonconformity_id)
    if finding["status"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RESPONSE_SUBMITTED finding may be reviewed")
    if domain.confirmed_assignment(finding["application_id"], user_id,
                                   role_types=("LEAD_ASSESSOR",)) is None:
        raise ApiError("ERR_NOT_ASSIGNED_TEAM_MEMBER")

    finding["reviewed_by_assessor_id"] = user_id
    finding["review_note"] = review_note
    finding["status"] = "RESPONSE_ACCEPTED" if outcome == "ACCEPT" else "OPEN"
    store.touch(finding)
    return single(store.public(finding))


@bp.post("/accreditation/nonconformities/<nonconformity_id>/verify-effectiveness")
@endpoint([LEAD_ASSESSOR, TECHNICAL_EXPERT])
def verify_effectiveness(user_id, role, nonconformity_id):
    payload = body()
    outcome = enum_field(payload, "outcome", VERIFY_OUTCOMES)
    evidence_count = int_field(payload, "verified_evidence_count", 0, None)

    finding = domain.find("nonconformities", nonconformity_id)
    if finding["status"] != "RESPONSE_ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a RESPONSE_ACCEPTED finding may be verified")
    if domain.confirmed_assignment(finding["application_id"], user_id,
                                   role_types=("LEAD_ASSESSOR", "TECHNICAL_ASSESSOR")) is None:
        raise ApiError("ERR_NOT_ASSIGNED_TEAM_MEMBER")
    if user_id == finding["reviewed_by_assessor_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the reviewer of the corrective action may not verify its effectiveness")
    if evidence_count < calc.MIN_EFFECTIVENESS_EVIDENCE[finding["classification"]]:
        raise ApiError("ERR_EFFECTIVENESS_EVIDENCE_INSUFFICIENT")

    application = store.get("applications", finding["application_id"])
    finding["verified_by_assessor_id"] = user_id
    finding["verified_evidence_count"] = evidence_count
    finding["effectiveness_outcome"] = outcome

    if outcome == "FAIL":
        finding["status"] = "OPEN"
        store.touch(finding)
        return single(store.public(finding))

    finding["closed_on"] = store.today_iso()
    finding["status"] = "CLOSED"
    store.touch(finding)

    application["nc_blocking_open_count"] -= 1
    application["nc_closed_count"] += 1
    store.touch(application)

    if application["status"] == "NC_OPEN" and application["nc_blocking_open_count"] == 0:
        application["status"] = "DECISION_PENDING"
        store.touch(application)
        domain.create_decision_record(application)

    return single(store.public(finding))


@bp.post("/accreditation/nonconformities/<nonconformity_id>/escalate")
@endpoint([ASSESSMENT_MANAGER])
def escalate_finding(user_id, role, nonconformity_id):
    finding = domain.find("nonconformities", nonconformity_id)
    if finding["status"] not in ("OPEN", "RESPONSE_SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an OPEN or RESPONSE_SUBMITTED finding may be escalated")
    if finding["classification"] not in ESCALABLE_CLASSIFICATIONS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a CRITICAL or MAJOR finding may be escalated")

    from validators import parse_date

    today = store.clock_date()
    if not finding["due_on"] or today <= parse_date(finding["due_on"], "due_on"):
        raise ApiError("ERR_NOT_YET_OVERDUE")

    finding["escalated_on"] = store.iso_date(today)
    finding["status"] = "ESCALATED"
    store.touch(finding)

    application = store.get("applications", finding["application_id"])
    organization = store.get("organizations", application["organization_id"])
    if organization is not None:
        domain.recompute_risk_at_decision(organization, application["id"])
    if application["origin_scope_id"]:
        scope = store.get("scopes", application["origin_scope_id"])
        if scope is not None and scope["status"] == "ACTIVE":
            domain.suspend_scope(scope, "escalated nonconformity",
                                 exclude_application_id=application["id"])

    return single(store.public(finding))


@bp.post("/accreditation/nonconformities/<nonconformity_id>/reopen")
@endpoint([ASSESSMENT_MANAGER])
def reopen_finding(user_id, role, nonconformity_id):
    payload = body()
    reason = string_field(payload, "reason", 1, 500)

    finding = domain.find("nonconformities", nonconformity_id)
    if finding["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only a CLOSED finding may be reopened")

    application = store.get("applications", finding["application_id"])
    if application["status"] not in ("NC_OPEN", "DECISION_PENDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the cycle no longer permits reopening a finding")

    finding["reopen_count"] += 1
    finding["closed_on"] = None
    finding["effectiveness_outcome"] = None
    finding["review_note"] = reason
    finding["status"] = "OPEN"
    store.touch(finding)

    application["nc_blocking_open_count"] += 1
    application["nc_closed_count"] -= 1
    store.touch(application)

    if application["status"] == "DECISION_PENDING":
        previous_round = application["decision_round"]
        application["status"] = "NC_OPEN"
        application["decision_round"] = previous_round + 1
        store.touch(application)
        for record in store.ordered(domain.decisions_of(application["id"])):
            if record["round"] == previous_round and record["status"] == "VOTING":
                record["status"] = "DEFERRED"
                record["outcome"] = "DEFER"
                record["decided_on"] = store.today_iso()
                store.touch(record)

    return single(store.public(finding))
