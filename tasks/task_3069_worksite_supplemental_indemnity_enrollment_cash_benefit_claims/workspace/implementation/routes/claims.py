"""Claim endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors as E
import services
from middleware import require_role
from response import success_object
from serializers import claim as claim_ser, claim_document
from util import add_months, get_body, get_or_404, list_response, parse_iso

bp = Blueprint("claims", __name__)

STORE = db.STORES["claims"]
DOCS = db.STORES["claim_documents"]


def _policy_of(claim_rec):
    return db.STORES["policies"][claim_rec["policy_id"]]


def _pinned_schedule(policy):
    sid = policy.get("benefit_schedule_id")
    if sid is None:
        return None
    return db.STORES["benefit_schedules"].get(sid)


@bp.route("/claims", methods=["POST"])
def create(role, user_id):
    require_role(role, {"PolicyholderServices", "ClaimsAdjuster"})
    body = get_body(["policy_id", "event_code", "service_date", "diagnosis_code", "claimed_occurrences"])
    policy = db.STORES["policies"].get(body["policy_id"])
    if policy is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "policy_id does not exist")
    sd = parse_iso(body["service_date"], "service_date")
    occ = body["claimed_occurrences"]
    if not isinstance(occ, int) or isinstance(occ, bool) or occ < 1:
        raise E.err(E.ERR_INVALID_REQUEST, "claimed_occurrences must be >= 1")
    rec = db.stamp_created({
        "policy_id": policy["id"],
        "event_code": body["event_code"],
        "service_date": db.format_ts(sd),
        "diagnosis_code": body["diagnosis_code"],
        "procedure_code": body.get("procedure_code"),
        "claimed_occurrences": occ,
        "provisional_payable_cents": None,
        "payable_amount_cents": None,
        "adjudicated_occurrences": None,
        "denial_reason": None,
        "status": "SUBMITTED",
    })
    STORE[rec["id"]] = rec
    return success_object(claim_ser(rec), status=201)


@bp.route("/claims/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    return success_object(claim_ser(rec))


@bp.route("/claims", methods=["GET"])
def list_all(role, user_id):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    filters = {
        "policy_id": request.args.get("policy_id"),
        "status": request.args.get("status"),
    }
    return list_response(STORE, filters, claim_ser)


@bp.route("/claims/<rid>/review", methods=["POST"])
def review(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] not in ("SUBMITTED", "APPEALED"):
        raise E.err(E.ERR_INVALID_STATE, f"Cannot review from {rec['status']}")
    policy = _policy_of(rec)
    if policy["status"] not in ("ACTIVE", "LAPSED", "PORTED"):
        raise E.err(E.ERR_POLICY_INACTIVE, "Policy is not in a reviewable status")
    schedule = _pinned_schedule(policy)
    item = services.find_benefit_item(schedule, rec["event_code"]) if schedule else None
    if item is None:
        raise E.err(E.ERR_EVENT_NOT_COVERED, "event_code not covered by pinned schedule")
    # PROVISIONAL variant
    year = int(rec["service_date"][0:4])
    _, provisional = services.claim_payable(policy, schedule, rec["event_code"], rec["claimed_occurrences"], year)
    rec["provisional_payable_cents"] = provisional
    rec["status"] = "UNDER_REVIEW"
    db.touch(rec)
    return success_object(claim_ser(rec))


def _deny(rec, reason):
    rec["denial_reason"] = reason
    rec["status"] = "DENIED"
    rec["_denied_at"] = db.format_ts(clock.now())
    db.touch(rec)


@bp.route("/claims/<rid>/adjudicate", methods=["POST"])
def adjudicate(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "UNDER_REVIEW":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot adjudicate from {rec['status']}")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise E.err(E.ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")
    if decision == "DENY":
        _deny(rec, "NOT_COVERED")
        return success_object(claim_ser(rec))

    # APPROVE gauntlet — documentation gates first, outstanding before missing proof
    docs = [d for d in DOCS.values() if d["claim_id"] == rec["id"]]
    if any(d["status"] == "RECEIVED" for d in docs):
        raise E.err(E.ERR_DOCUMENTS_PENDING, "Claim has documents not yet ACCEPTED")
    has_proof = any(
        d["status"] == "ACCEPTED" and d["doc_type"] in ("DIAGNOSIS_PROOF", "ATTENDING_PHYSICIAN_STATEMENT")
        for d in docs
    )
    if not has_proof:
        raise E.err(E.ERR_INSUFFICIENT_DOCUMENTS, "No ACCEPTED diagnosis proof or APS on the claim")

    policy = _policy_of(rec)
    schedule = _pinned_schedule(policy)
    item = services.find_benefit_item(schedule, rec["event_code"])
    employee = db.STORES["employees"][policy["employee_id"]]
    service_dt = parse_iso(rec["service_date"])

    # pre-existing exclusion: auto-deny with PRE_EXISTING, surfaced as ERR_PRE_EXISTING_EXCLUSION
    if rec["diagnosis_code"] in (employee.get("preexisting_diagnosis_codes") or []):
        exclusion_end = add_months(parse_iso(policy["coverage_start_date"]), schedule["preexisting_exclusion_months"])
        if service_dt < exclusion_end:
            _deny(rec, "PRE_EXISTING")
            raise E.err(E.ERR_PRE_EXISTING_EXCLUSION, "Pre-existing diagnosis inside the exclusion window")

    # fiscal caps: zero remaining capacity -> auto-deny CAP_EXHAUSTED
    year = int(rec["service_date"][0:4])
    paid_this_year = (
        policy.get("paid_occurrences_by_year", {}).get(str(year), {}).get(rec["event_code"], 0)
    )
    remaining_occ = item["max_occurrences_per_year"] - paid_this_year
    remaining_life = item["lifetime_max_cents"] - policy.get("lifetime_paid_cents", 0)
    if remaining_occ <= 0 or remaining_life <= 0:
        _deny(rec, "CAP_EXHAUSTED")
        raise E.err(E.ERR_CAP_EXHAUSTED, "Yearly occurrence cap or lifetime max exhausted")

    # FINAL variant
    credited, payable = services.claim_payable(policy, schedule, rec["event_code"], rec["claimed_occurrences"], year)
    rec["payable_amount_cents"] = payable
    rec["adjudicated_occurrences"] = credited
    rec["status"] = "APPROVED"
    db.touch(rec)
    return success_object(claim_ser(rec))


@bp.route("/claims/<rid>/pay", methods=["POST"])
def pay(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "APPROVED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot pay from {rec['status']}")
    policy = _policy_of(rec)
    if policy["status"] not in ("ACTIVE", "LAPSED", "PORTED"):
        raise E.err(E.ERR_POLICY_INACTIVE, "Policy is not in a payable status")
    rec["status"] = "PAID"
    db.touch(rec)
    services.ledger_pay(policy, rec)
    return success_object(claim_ser(rec))


@bp.route("/claims/<rid>/appeal", methods=["POST"])
def appeal(role, user_id, rid):
    require_role(role, {"PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "DENIED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot appeal from {rec['status']}")
    denied_at = parse_iso(rec["_denied_at"]) if rec.get("_denied_at") else clock.now()
    if clock.now() - denied_at > timedelta(days=180):
        raise E.err(E.ERR_APPEAL_WINDOW_EXPIRED, "Appeal filed more than 180 days after denial")
    rec["status"] = "APPEALED"
    db.touch(rec)
    return success_object(claim_ser(rec))


@bp.route("/claims/<rid>/void", methods=["POST"])
def void(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] not in ("APPROVED", "PAID"):
        raise E.err(E.ERR_INVALID_STATE, f"Cannot void from {rec['status']}")
    was_paid = rec["status"] == "PAID"
    rec["status"] = "VOIDED"
    db.touch(rec)
    if was_paid:
        policy = _policy_of(rec)
        services.ledger_void_paid(policy, rec)
    return success_object(claim_ser(rec))


@bp.route("/claims/<rid>/documents", methods=["GET"])
def list_documents(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    get_or_404(STORE, rid)
    filters = {
        "claim_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(DOCS, filters, claim_document)
