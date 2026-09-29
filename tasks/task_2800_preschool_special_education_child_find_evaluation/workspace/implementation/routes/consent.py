"""Parental consent decisions on both consent kinds (PRD sections 3.4 and 3.7)."""
from flask import Blueprint

from db import clock_date, db, now_utc, touch
from errors import ApiError
from middleware import endpoint
from response import object_response
from routes.common import matches, paged
from services import derive, rules
from validation import CONSENT_DECISION, CONSENT_KIND, body, q_enum, q_str, req_enum

bp = Blueprint("consent", __name__)

READ_ROLES = (
    "ChildFindCoordinator",
    "EvaluationChair",
    "PlacementAdministrator",
    "Parent",
    "DistrictAdmin",
)

# The ConsentRecord state machine, kind-agnostic; the kind restriction on a
# revocation is rung 29, consulted after this rung-11 check.
DECISION_TRANSITIONS = (
    ("PENDING", "GRANTED"),
    ("PENDING", "REFUSED"),
    ("GRANTED", "REVOKED"),
)


@bp.post("/consent-records/<record_id>/decision")
@endpoint("ChildFindCoordinator", "Parent", "DistrictAdmin")
def record_decision(record_id):
    data = body()
    decision = req_enum(data, "decision", CONSENT_DECISION)

    record = rules.fetch("consent_records", record_id)               # rung 4
    referral = db.referrals[record["referral_id"]]
    rules.require_guardian(referral["child_id"])                     # rung 6

    if (record["decision"], decision) not in DECISION_TRANSITIONS:   # rung 11
        raise ApiError(
            "ERR_INVALID_CONSENT_STATE",
            "A %s consent record may not move to %s" % (record["decision"], decision),
        )
    if decision == "REVOKED" and record["kind"] != "EVALUATION_CONSENT":   # rung 29
        raise ApiError(
            "ERR_CONSENT_NOT_REVOCABLE",
            "A SERVICE_CONSENT record has no revocation path; use the plan lifecycle",
        )

    record["decision"] = decision
    record["decided_at"] = now_utc()
    touch(record)

    if record["kind"] == "EVALUATION_CONSENT":
        _apply_evaluation_decision(referral, decision)
    else:
        _apply_service_decision(record, decision)
    return object_response(derive.consent_out(record))


def _apply_evaluation_decision(referral, decision):
    if decision == "GRANTED":
        rules.grant_evaluation_consent(referral)
        return
    if decision == "REFUSED":
        referral["intake_status"] = "DECLINED"
        referral["consent_status"] = "REFUSED"
        touch(referral)
        return
    # REVOKED: the pinned evaluation_due_date is retained as the historical
    # deadline, and the deepest cascade in the system starts here.
    referral["intake_status"] = "WITHDRAWN"
    referral["consent_status"] = "REVOKED"
    touch(referral)
    rules.cancel_cases_of_referral(referral)


def _apply_service_decision(record, decision):
    plan = db.service_plans.get(record.get("service_plan_id"))
    if plan is None or plan["status"] != "PENDING_PARENT_CONSENT":
        return
    if decision == "GRANTED":
        plan["status"] = "ACTIVE"
        plan["start_date"] = clock_date()
        touch(plan)
        return
    plan["status"] = "DECLINED"
    touch(plan)
    rules.discontinue_plan_lines(plan)


@bp.get("/consent-records/<record_id>")
@endpoint(*READ_ROLES)
def get_consent_record(record_id):
    return object_response(derive.consent_out(rules.fetch("consent_records", record_id)))


@bp.get("/consent-records")
@endpoint(*READ_ROLES)
def list_consent_records():
    referral_id = q_str("referral_id")
    interpreter_id = q_str("interpreter_provider_id")
    plan_id = q_str("service_plan_id")
    kind = q_enum("kind", CONSENT_KIND)
    decision = q_enum("decision", CONSENT_DECISION)
    rows = [
        r
        for r in db.consent_records.values()
        if matches(r, "referral_id", referral_id)
        and matches(r, "interpreter_provider_id", interpreter_id)
        and matches(r, "service_plan_id", plan_id)
        and matches(r, "kind", kind)
        and matches(r, "decision", decision)
    ]
    return paged(rows, derive.consent_out)
