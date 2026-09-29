"""Claims: filing, the review cycle, adjudication, payment and the
compensating reversal (PRD 3.7)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import ledger
import validate
import views
from errors import fail
from store import base_record, db, sorted_rows, touch

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("DAMAGE_WAIVER", "AIR_QUALITY_GUARANTEE")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED",
                  "DENIED", "PAID", "PAYMENT_REVERSED", "WITHDRAWN")
DECISIONS = ("APPROVE", "DENY")
FILER_ROLES = ["Resident", "PropertyManager", "ProgramOperator"]


def _claim_subscription(uid, role, claim):
    sub = db.subscriptions[claim["subscription_id"]]
    guards.own_subscription(uid, role, sub)
    return sub


def _active_entitlement(sub, benefit_code):
    for row in calc.entitlements_of(sub["id"]):
        if row["benefit_code"] == benefit_code and row["state"] == "ACTIVE":
            return row
    return None


@bp.post("/claims")
def file_claim():
    uid, role = guards.auth(FILER_ROLES)
    body = validate.json_body()
    sub = guards.get_subscription(body.get("subscription_id"))
    guards.own_subscription(uid, role, sub)
    claim_type = validate.req_enum(body, "claim_type", CLAIM_TYPES)
    incident_date = validate.req_date(body, "incident_date")
    requested = validate.req_int(body, "requested_amount_cents", 1)
    description = validate.req_string(body, "description", 1, 500)

    if sub["status"] in ("PENDING_SETUP", "VOIDED"):
        fail("ERR_SUBSCRIPTION_STATE_INVALID",
             "a subscription that never activated cannot back a claim")
    if _active_entitlement(sub, claim_type) is None:
        fail("ERR_BENEFIT_NOT_ENTITLED",
             "the entitlement backing this claim type is not ACTIVE")
    activated = clock.parse_instant(sub["activated_at"]).date()
    today = clock.today()
    if (incident_date < activated or incident_date > today
            or (today - incident_date).days > calc.CLAIM_FILING_WINDOW_DAYS):
        fail("ERR_OUTSIDE_COVERAGE_WINDOW",
             "the incident date falls outside the coverage window")
    if requested > calc.CLAIM_HARD_CAP_CENTS:
        fail("ERR_CLAIM_AMOUNT_EXCEEDS_CAP",
             "requested_amount_cents exceeds the program hard cap")

    rec = base_record()
    rec["subscription_id"] = sub["id"]
    rec["claim_type"] = claim_type
    rec["incident_date"] = clock.fmt_date(incident_date)
    rec["requested_amount_cents"] = requested
    rec["description"] = description
    rec["provisional_amount_cents"] = None
    rec["approved_amount_cents"] = None
    rec["triaged_by_user_id"] = None
    rec["decided_by_user_id"] = None
    rec["info_request_round"] = 0
    rec["paid_at"] = None
    rec["reversal_reason"] = None
    rec["status"] = "SUBMITTED"
    db.claims[rec["id"]] = rec
    return envelope.object_response(views.claim_view(rec), 201)


@bp.get("/claims/<claim_id>")
def read_claim(claim_id):
    uid, role = guards.auth(["ProgramOperator", "ClaimsAdjuster",
                             "PropertyManager", "Resident"])
    rec = guards.get_claim(claim_id)
    _claim_subscription(uid, role, rec)
    return envelope.object_response(views.claim_view(rec))


@bp.get("/claims")
def list_claims():
    guards.auth(["ProgramOperator", "ClaimsAdjuster"])
    limit, offset, filters = guards.pagination(
        {"status": CLAIM_STATUSES, "claim_type": CLAIM_TYPES},
        ("subscription_id",))
    rows = sorted_rows([c for c in db.claims.values()
                        if all(c[k] == v for k, v in filters.items())])
    return envelope.list_response([views.claim_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/claims/<claim_id>/triage")
def triage(claim_id):
    uid, _role = guards.auth(["ClaimsAdjuster"])
    rec = guards.get_claim(claim_id)
    if rec["status"] != "SUBMITTED":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not SUBMITTED")

    sub = db.subscriptions[rec["subscription_id"]]
    rec["provisional_amount_cents"] = calc.provisional_amount(rec, sub)
    rec["triaged_by_user_id"] = uid
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/request-info")
def request_info(claim_id):
    guards.auth(["ClaimsAdjuster"])
    rec = guards.get_claim(claim_id)
    body = validate.json_body()
    question = validate.req_text(body, "question")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not UNDER_REVIEW")
    if rec["info_request_round"] >= calc.MAX_INFO_REQUEST_ROUNDS:
        fail("ERR_INFO_REQUEST_LIMIT",
             "the claim has exhausted its information-request rounds")

    rec["_question"] = question
    rec["info_request_round"] = rec["info_request_round"] + 1
    rec["status"] = "INFO_REQUESTED"
    touch(rec)
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/resubmit")
def resubmit(claim_id):
    uid, role = guards.auth(FILER_ROLES)
    rec = guards.get_claim(claim_id)
    _claim_subscription(uid, role, rec)
    body = validate.json_body()
    description = validate.req_string(body, "description", 1, 500)
    if rec["status"] != "INFO_REQUESTED":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not INFO_REQUESTED")

    # PRD 3.7: resubmission explicitly does NOT recompute
    # provisional_amount_cents - the triage-time freeze survives the loop.
    rec["description"] = description
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/decide")
def decide(claim_id):
    uid, _role = guards.auth(["ClaimsAdjuster"])
    rec = guards.get_claim(claim_id)
    body = validate.json_body()
    decision = validate.req_enum(body, "decision", DECISIONS)
    note = validate.req_text(body, "decision_note")
    if rec["status"] != "UNDER_REVIEW":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not UNDER_REVIEW")
    if rec["triaged_by_user_id"] is not None and uid == rec["triaged_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the adjuster who triaged this claim may not decide it")

    sub = db.subscriptions[rec["subscription_id"]]
    if decision == "APPROVE":
        if _active_entitlement(sub, rec["claim_type"]) is None:
            fail("ERR_BENEFIT_NOT_ENTITLED",
                 "the entitlement backing this claim is no longer ACTIVE")
        rec["approved_amount_cents"] = calc.approved_amount(rec, sub)
        rec["status"] = "APPROVED"
    else:
        rec["approved_amount_cents"] = 0
        rec["status"] = "DENIED"
    rec["_decision_note"] = note
    rec["decided_by_user_id"] = uid
    touch(rec)
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/pay")
def pay(claim_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_claim(claim_id)
    if rec["status"] != "APPROVED":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not APPROVED")
    if not rec["approved_amount_cents"]:
        fail("ERR_CLAIM_STATE_INVALID",
             "an approved amount of zero cannot be disbursed")

    sub = db.subscriptions[rec["subscription_id"]]
    rec["paid_at"] = clock.now_iso()
    rec["status"] = "PAID"
    touch(rec)
    ledger.post_one_off(sub, "CLAIM_PAYOUT", -rec["approved_amount_cents"],
                        "claim payout", rec["id"])
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/reverse-payment")
def reverse_payment(claim_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_claim(claim_id)
    body = validate.json_body()
    reason = validate.req_text(body, "reversal_reason")
    if rec["status"] != "PAID":
        fail("ERR_CLAIM_STATE_INVALID", "the claim is not PAID")

    sub = db.subscriptions[rec["subscription_id"]]
    # approved_amount_cents is deliberately left unchanged so the two ledger
    # legs sum to exactly zero (PRD 3.7).
    rec["reversal_reason"] = reason
    rec["status"] = "PAYMENT_REVERSED"
    touch(rec)
    ledger.post_one_off(sub, "CLAIM_PAYOUT_REVERSAL",
                        rec["approved_amount_cents"],
                        "claim payout reversal", rec["id"])
    return envelope.object_response(views.claim_view(rec))


@bp.post("/claims/<claim_id>/withdraw")
def withdraw(claim_id):
    uid, role = guards.auth(FILER_ROLES)
    rec = guards.get_claim(claim_id)
    _claim_subscription(uid, role, rec)
    body = validate.json_body()
    reason = validate.req_text(body, "withdraw_reason")
    if rec["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
        fail("ERR_CLAIM_STATE_INVALID",
             "only an undecided claim can be withdrawn")

    rec["_withdraw_reason"] = reason
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return envelope.object_response(views.claim_view(rec))
