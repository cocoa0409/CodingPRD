"""Settlement negotiation loop, consent to settle, hammer clause and payment (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, g

import constants as C
from auth import claim as fetch_claim, deny_self_decision, endpoint, find
from auth import negotiation as fetch_negotiation, own_negotiation
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, body, r2, v_date, v_enum, v_int, v_money, v_str
from services import claims as claims_svc, rating

bp = Blueprint("negotiations", __name__, url_prefix=C.API_PREFIX)

PAYABLE_STATUSES = ("AUTHORITY_GRANTED", "CONSENT_GRANTED", "HAMMER_INVOKED")


def negotiations_of(claim_id):
    return [n for n in all_of(db.negotiations) if n["claim_id"] == claim_id]


@bp.post("/claims/<record_id>/settlement-negotiations")
@endpoint([C.R_ADJUSTER, C.R_APPROVER])
def open_negotiation(record_id):
    claim = fetch_claim(record_id)

    payload = body()
    proposed_amount = v_money(payload, "proposed_amount", minimum=ZERO)
    authority_requested = v_money(payload, "authority_requested", minimum=ZERO)
    expected_version = v_int(payload, "expected_claim_version")

    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")

    if claim["claim_status"] not in ("INVESTIGATION", "LITIGATION"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    if claim["coverage_status"] == "DENIED" or (
        claim["policy_term_id"] is None and claim["tail_endorsement_id"] is None
    ):
        raise ApiError("ERR_COVERAGE_DENIED_NO_DEFENSE")

    policy = rating.responding_policy(claim)
    if policy is None:
        raise ApiError("ERR_COVERAGE_DENIED_NO_DEFENSE")

    headroom = r2(policy["limit_per_claim"] - claim["paid_indemnity"])
    if proposed_amount > headroom:
        raise ApiError("ERR_PER_CLAIM_LIMIT_EXCEEDED")

    for other in negotiations_of(claim["id"]):
        if other["status"] not in ("PAID", "ABANDONED"):
            other["status"] = "ABANDONED"
            touch(other)

    record = new_record(
        {
            "claim_id": claim["id"],
            "proposed_amount": proposed_amount,
            "authority_requested": authority_requested,
            "authority_granted": None,
            "status": "AUTHORITY_REQUESTED",
            "round_index": 1,
            "prepared_by_user_id": g.user_id,
            "approved_by_user_id": None,
            "approver_note": None,
            "consent_clause_applied": policy["consent_to_settle_clause"],
            "physician_response": None,
            "veto_reason": None,
            "consent_requested_at": None,
            "hammer_invoked": False,
            "hammer_exposure_estimate": r2(ZERO),
            "insured_share_amount": r2(ZERO),
            "carrier_share_amount": r2(ZERO),
            "notice_sent_on": None,
            "paid_amount": None,
            "payment_date": None,
        }
    )
    db.negotiations[record["id"]] = record
    touch(claim)
    return created(record)


@bp.get("/settlement-negotiations/<record_id>")
@endpoint(C.CARRIER_AND_INSURED)
def get_negotiation(record_id):
    candidate = find(db.negotiations, record_id)
    if candidate is not None:
        own_negotiation(candidate)
    return ok(fetch_negotiation(record_id))


@bp.get("/settlement-negotiations")
@endpoint(C.CARRIER_ROLES)
def list_negotiations():
    limit, offset = pagination()
    records = all_of(db.negotiations)
    records = common.eq(records, "claim_id", common.arg("claim_id"))
    records = common.eq(records, "status", common.arg("status"))
    records = common.eq(
        records, "consent_clause_applied", common.arg("consent_clause_applied")
    )
    return listing(records, limit, offset)


@bp.post("/settlement-negotiations/<record_id>/authority-decision")
@endpoint([C.R_APPROVER])
def authority_decision(record_id):
    candidate = find(db.negotiations, record_id)
    if candidate is not None:
        deny_self_decision(candidate)

    payload = body()
    decision = v_enum(payload, "decision", C.AUTHORITY_DECISIONS)
    approver_note = v_str(payload, "approver_note")
    granted_amount = v_money(
        payload, "granted_amount", required=False, minimum=None
    )

    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] != "AUTHORITY_REQUESTED":
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")

    if decision == "GRANT":
        if granted_amount is None or granted_amount <= ZERO:
            raise ApiError("ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST")
        if granted_amount > negotiation["authority_requested"]:
            raise ApiError("ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST")
    else:
        if granted_amount is not None:
            raise ApiError("ERR_AUTHORITY_GRANT_EXCEEDS_REQUEST")

    negotiation["approver_note"] = approver_note
    negotiation["approved_by_user_id"] = g.user_id
    if decision == "GRANT":
        negotiation["authority_granted"] = granted_amount
        negotiation["status"] = "AUTHORITY_GRANTED"
    else:
        negotiation["status"] = "AUTHORITY_DENIED"
    touch(negotiation)
    return ok(negotiation)


@bp.post("/settlement-negotiations/<record_id>/consent-request")
@endpoint([C.R_ADJUSTER])
def consent_request(record_id):
    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] != "AUTHORITY_GRANTED":
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")
    if negotiation["consent_clause_applied"] == "NONE":
        raise ApiError("ERR_CONSENT_REQUIRED")
    negotiation["status"] = "CONSENT_REQUESTED"
    negotiation["consent_requested_at"] = db.logical_now()
    touch(negotiation)
    return ok(negotiation)


@bp.post("/settlement-negotiations/<record_id>/consent-response")
@endpoint([C.R_INSURED])
def consent_response(record_id):
    candidate = find(db.negotiations, record_id)
    if candidate is not None:
        own_negotiation(candidate)

    payload = body()
    response = v_enum(payload, "response", C.CONSENT_RESPONSES)
    veto_reason = v_str(payload, "veto_reason", required=(response == "VETOED"))

    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] != "CONSENT_REQUESTED":
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")

    negotiation["physician_response"] = response
    if response == "CONSENTED":
        negotiation["status"] = "CONSENT_GRANTED"
    else:
        negotiation["status"] = "VETOED"
        negotiation["veto_reason"] = veto_reason
    touch(negotiation)
    return ok(negotiation)


@bp.post("/settlement-negotiations/<record_id>/revision")
@endpoint([C.R_ADJUSTER])
def revise_negotiation(record_id):
    payload = body()
    proposed_amount = v_money(payload, "proposed_amount", minimum=ZERO)
    authority_requested = v_money(payload, "authority_requested", minimum=ZERO)

    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] not in ("VETOED", "AUTHORITY_DENIED"):
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")

    claim = db.claims.get(negotiation["claim_id"])
    if claim is None or claim["claim_status"] not in ("INVESTIGATION", "LITIGATION"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    negotiation["round_index"] = int(negotiation["round_index"]) + 1
    negotiation["proposed_amount"] = proposed_amount
    negotiation["authority_requested"] = authority_requested
    negotiation["authority_granted"] = None
    negotiation["approved_by_user_id"] = None
    negotiation["physician_response"] = None
    negotiation["veto_reason"] = None
    negotiation["prepared_by_user_id"] = g.user_id
    negotiation["status"] = "AUTHORITY_REQUESTED"
    touch(negotiation)
    return ok(negotiation)


@bp.post("/settlement-negotiations/<record_id>/hammer-invocation")
@endpoint([C.R_APPROVER])
def invoke_hammer(record_id):
    payload = body()
    notice_sent_on = v_date(payload, "notice_sent_on")

    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] != "VETOED":
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")
    if negotiation["consent_clause_applied"] != "HAMMER":
        raise ApiError("ERR_HAMMER_NOT_AVAILABLE")

    claim = db.claims[negotiation["claim_id"]]
    policy = rating.responding_policy(claim)
    proposed = negotiation["proposed_amount"]
    projected = proposed * C.HAMMER_EXPOSURE_MULTIPLIER
    if policy is not None and projected > policy["limit_per_claim"]:
        projected = policy["limit_per_claim"]
    exposure = r2(projected)
    excess = exposure - proposed
    if excess < ZERO:
        excess = ZERO
    insured_share = r2(excess * C.HAMMER_INSURED_SHARE_PCT)
    carrier_share = r2(exposure - insured_share)

    negotiation["status"] = "HAMMER_INVOKED"
    negotiation["hammer_invoked"] = True
    negotiation["notice_sent_on"] = notice_sent_on
    negotiation["hammer_exposure_estimate"] = exposure
    negotiation["insured_share_amount"] = insured_share
    negotiation["carrier_share_amount"] = carrier_share
    touch(negotiation)

    claim["insured_share_receivable"] = r2(
        claim["insured_share_receivable"] + insured_share
    )
    touch(claim)
    return ok(negotiation)


@bp.post("/settlement-negotiations/<record_id>/payment")
@endpoint([C.R_ADJUSTER])
def pay_settlement(record_id):
    payload = body()
    payment_date = v_date(payload, "payment_date")

    negotiation = fetch_negotiation(record_id)
    if negotiation["status"] not in PAYABLE_STATUSES:
        raise ApiError("ERR_NEGOTIATION_STATE_INVALID")

    if negotiation["status"] == "AUTHORITY_GRANTED" and negotiation[
        "consent_clause_applied"
    ] != "NONE":
        raise ApiError("ERR_CONSENT_REQUIRED")

    granted = negotiation["authority_granted"]
    if granted is None or negotiation["proposed_amount"] > granted:
        raise ApiError("ERR_AUTHORITY_INSUFFICIENT")

    if negotiation["status"] == "HAMMER_INVOKED":
        disbursed = r2(negotiation["carrier_share_amount"])
    else:
        disbursed = r2(negotiation["proposed_amount"])

    claim = db.claims[negotiation["claim_id"]]
    term = rating.responding_term(claim)
    policy = rating.responding_policy(claim)
    if term is not None and disbursed > term["aggregate_limit_remaining"]:
        raise ApiError("ERR_AGGREGATE_LIMIT_EXCEEDED")
    if policy is not None and disbursed > r2(
        policy["limit_per_claim"] - claim["paid_indemnity"]
    ):
        raise ApiError("ERR_PER_CLAIM_LIMIT_EXCEEDED")

    negotiation["status"] = "PAID"
    negotiation["paid_amount"] = disbursed
    negotiation["payment_date"] = payment_date
    touch(negotiation)

    claims_svc.resolve_claim(
        claim,
        "SETTLED",
        payment_date,
        negotiation=negotiation,
        paid_amount=disbursed,
    )
    return ok(negotiation)
