"""Claims: intake assessment, recurrence groups, triage and appeals."""

from flask import Blueprint

import config
import derive
import serializers
import timeutil
from errors import ApiError
from response import object_response, paginate
from routes.enrollments import lookup_enrollment
from services import cascades
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("claims", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_BILLING_OPS,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_APPEALS_OFFICER,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)
SINGLE_READ_ROLES = READ_ROLES + (config.ROLE_POLICYHOLDER, config.ROLE_NETWORK_CONTRACTOR)

CREATE_SPEC = {
    "enrollment_id": Field("uuid", required=True),
    "line_type": Field("enum", required=True, enum=config.LINE_TYPES),
    "defect_location": Field("enum", required=True, enum=config.DEFECT_LOCATIONS),
    "urgency": Field("enum", required=True, enum=config.URGENCIES),
    "incident_description": Field("string", required=True, min_len=1, max_len=500),
    "recurrence_of_claim_id": Field("uuid"),
}

TRIAGE_SPEC = {
    "decision": Field("enum", required=True, enum=config.TRIAGE_DECISIONS),
    "coverage_note": Field("string", required=True, min_len=1, max_len=1000),
    "denial_reason": Field("enum", enum=config.DENIAL_REASONS),
}

APPEAL_SPEC = {"appeal_reason": Field("string", required=True, min_len=1, max_len=1000)}

APPEAL_DECISION_SPEC = {
    "decision": Field("enum", required=True, enum=config.APPEAL_DECISIONS),
    "rationale": Field("string", required=True, min_len=1, max_len=1000),
}

# The refusal that answers an approval attempt on each uncovered assessment.
APPROVAL_REFUSALS = {
    "COVERAGE_INACTIVE": "ERR_ENROLLMENT_NOT_ACTIVE",
    "WAITING_PERIOD": "ERR_WAITING_PERIOD_NOT_ELAPSED",
    "OWNERSHIP_INELIGIBLE": "ERR_OWNERSHIP_NOT_ELIGIBLE",
    "PRE_EXISTING": "ERR_PRE_EXISTING_CONDITION",
    "CAP_EXHAUSTED": "ERR_ANNUAL_CAP_EXHAUSTED",
}


def lookup_claim(claim_id):
    claim = store.claims.get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "No claim with id %s" % claim_id)
    return claim


@bp.post("/claims")
def create_claim():
    current_user_id()
    require_role(config.ROLE_CUSTOMER_SERVICE_REP, config.ROLE_POLICYHOLDER)
    body = parse_body(CREATE_SPEC)

    enrollment = lookup_enrollment(body["enrollment_id"])
    recurrence = None
    if body["recurrence_of_claim_id"]:
        recurrence = lookup_claim(body["recurrence_of_claim_id"])

    product = derive.product_of_enrollment(enrollment)
    if product is not None and body["line_type"] != product["line_type"]:
        raise ApiError("ERR_INVALID_REQUEST", "line_type must match the enrolled product's line type")
    if enrollment["coverage_status"] in ("CANCELLED", "LAPSED"):
        raise ApiError("ERR_ENROLLMENT_TERMINAL", "The policy is %s" % enrollment["coverage_status"])

    reported_at = store.now()
    if recurrence is not None:
        if recurrence["enrollment_id"] != enrollment["id"] or recurrence["line_type"] != body["line_type"]:
            raise ApiError("ERR_INVALID_RECURRENCE_LINK", "The referenced claim is not on the same policy and line")
        referenced_reported = timeutil.parse_instant(recurrence["reported_at"])
        if timeutil.floor_days_between_instants(referenced_reported, reported_at) > config.RECURRENCE_WINDOW_DAYS:
            raise ApiError("ERR_INVALID_RECURRENCE_LINK", "The referenced claim is older than 30 days")

    record = create_record(
        store.claims,
        {
            "enrollment_id": enrollment["id"],
            "recurrence_of_claim_id": recurrence["id"] if recurrence else None,
            "occurrence_root_claim_id": None,
            "line_type": body["line_type"],
            "defect_location": body["defect_location"],
            "urgency": body["urgency"],
            "incident_description": body["incident_description"],
            "reported_at": store.now_iso(),
            "status": "TRIAGE",
            "denial_reason": None,
            "triage_decided_by_user_id": None,
            "triage_decided_at": None,
            "denied_at": None,
            "appeal_opened_at": None,
            "appeal_source": None,
            "appeal_decided_by_user_id": None,
            "appeal_count": 0,
            "sla_deadline_at": None,
        },
    )
    # The occurrence root is the transitive root of the recurrence chain.
    if recurrence is not None:
        record["occurrence_root_claim_id"] = recurrence.get("occurrence_root_claim_id") or recurrence["id"]
    else:
        record["occurrence_root_claim_id"] = record["id"]
    return object_response(serializers.claim(record), 201)


@bp.get("/claims")
def list_claims():
    current_user_id()
    require_role(*READ_ROLES)
    enrollment_id = filter_value("enrollment_id")
    recurrence_id = filter_value("recurrence_of_claim_id")
    status = filter_enum("status", config.CLAIM_STATUSES)

    def matches(claim):
        if enrollment_id is not None and claim["enrollment_id"] != enrollment_id:
            return False
        if recurrence_id is not None and claim["recurrence_of_claim_id"] != recurrence_id:
            return False
        if status is not None and claim["status"] != status:
            return False
        return True

    return paginate(ordered(store.claims, matches), serializers.claim)


@bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    current_user_id()
    require_role(*SINGLE_READ_ROLES)
    require_path_uuid(claim_id)
    return object_response(serializers.claim(lookup_claim(claim_id)))


@bp.post("/claims/<claim_id>/triage-decision")
def triage_claim(claim_id):
    user_id = current_user_id()
    require_role(config.ROLE_CLAIMS_ADJUSTER)
    require_path_uuid(claim_id)
    body = parse_body(TRIAGE_SPEC)
    if body["decision"] == "DENY" and body["denial_reason"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason is required when denying a claim")

    claim = lookup_claim(claim_id)
    if claim["status"] != "TRIAGE":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a claim in TRIAGE may be triaged")

    assessment = derive.eligibility_assessment(claim)
    if body["decision"] == "APPROVE":
        refusal = APPROVAL_REFUSALS.get(assessment)
        if refusal is not None:
            raise ApiError(refusal, "The claim was assessed %s and may not be approved" % assessment)
        claim["status"] = "APPROVED"
    else:
        reason = body["denial_reason"]
        if assessment == "ELIGIBLE":
            permitted = reason == "NOT_COVERED_SEGMENT"
        else:
            permitted = reason == assessment
        if not permitted:
            raise ApiError(
                "ERR_DENIAL_REASON_UNSUPPORTED",
                "denial_reason %s contradicts the assessment %s" % (reason, assessment),
            )
        claim["status"] = "DENIED"
        claim["denial_reason"] = reason
        claim["denied_at"] = store.now_iso()

    claim["triage_decided_by_user_id"] = user_id
    claim["triage_decided_at"] = store.now_iso()
    touch(claim)
    return object_response(serializers.claim(claim))


@bp.post("/claims/<claim_id>/appeals")
def appeal_claim(claim_id):
    user_id = current_user_id()
    require_role(config.ROLE_POLICYHOLDER)
    require_path_uuid(claim_id)
    parse_body(APPEAL_SPEC)
    claim = lookup_claim(claim_id)

    enrollment = derive.enrollment_of_claim(claim)
    if enrollment is None or user_id != enrollment["premises_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the policyholder at this address may appeal")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a DENIED claim may be appealed")
    if claim["appeal_count"] >= config.APPEAL_LIMIT:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED", "The claim has already been appealed twice")
    denied_at = timeutil.parse_instant(claim["denied_at"])
    deadline = timeutil.add_days(denied_at, config.APPEAL_WINDOW_DAYS)
    if store.now() > deadline:
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", "The 30-day appeal window has closed")

    cascades.open_appeal(claim, "POLICYHOLDER")
    return object_response(serializers.claim(claim))


@bp.post("/claims/<claim_id>/appeal-decision")
def decide_appeal(claim_id):
    user_id = current_user_id()
    require_role(config.ROLE_APPEALS_OFFICER)
    require_path_uuid(claim_id)
    body = parse_body(APPEAL_DECISION_SPEC)
    claim = lookup_claim(claim_id)

    if claim["triage_decided_by_user_id"] is not None and user_id == claim["triage_decided_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The deciding adjuster may not hear the appeal")
    if claim["status"] != "APPEAL_OPEN":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Only a claim in APPEAL_OPEN may be decided")

    if body["decision"] == "OVERTURN":
        claim["status"] = "APPROVED"
        claim["denial_reason"] = None
        claim["denied_at"] = None
    elif body["decision"] == "REMAND":
        claim["status"] = "DENIED"
        claim["denied_at"] = store.now_iso()
    else:
        claim["status"] = "APPEAL_UPHELD_DENIAL"
    claim["appeal_decided_by_user_id"] = user_id
    touch(claim)

    cascades.refresh_retention_hold(derive.enrollment_of_claim(claim))
    return object_response(serializers.claim(claim))
