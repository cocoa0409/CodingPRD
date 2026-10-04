"""Referral endpoints -- cross-brand attribution (PRD 3.5, 2.8, 3.9).

POST /franchise/referrals, GET /franchise/referrals[/{id}]
POST /franchise/referrals/{id}/accept|decline|complete|dispute|resolve-dispute|settle
"""
from flask import Blueprint

import derived
from auth import guard, require_referral_party, require_receiving_franchisee
from config import REFERRAL_EXPIRY_HOURS
from errors import ApiError
from fetch import get_agreement, get_referral, paged
from response import created, ok
from store import common_fields, db, hours_from, now_dt, parse_instant, touch
from validate import (
    body,
    opt_money,
    reject_unknown,
    req_id,
    req_int,
    req_rate,
    req_str,
)
from calculations import referral_fee
from money import as_number, dec

bp = Blueprint("referrals", __name__)

CREATE_INPUT = [
    "referral_code", "originating_agreement_id", "receiving_agreement_id",
    "customer_household_ref", "job_description", "estimated_job_value_cents",
    "referral_fee_rate",
]


def _started_referral(referral_id):
    referral = get_referral(referral_id)
    if referral.get("status") in ("DECLINED", "SETTLED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return referral


def _require_status(referral, allowed):
    if referral.get("status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _receiving_agreement(referral):
    return get_agreement(referral.get("receiving_agreement_id"))


def _originating_agreement(referral):
    return get_agreement(referral.get("originating_agreement_id"))


@bp.post("/franchise/referrals")
def create_referral():
    _, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    referral_code = req_str(b, "referral_code")
    if any(r.get("referral_code") == referral_code for r in db.referrals.values()):
        raise ApiError("ERR_DUPLICATE_REFERRAL_CODE")
    originating_id = req_id(b, "originating_agreement_id")
    receiving_id = req_id(b, "receiving_agreement_id")
    customer_ref = req_str(b, "customer_household_ref")
    job_description = req_str(b, "job_description")
    estimated_value = req_int(b, "estimated_job_value_cents", minimum=0)
    fee_rate = req_rate(b, "referral_fee_rate")

    get_agreement(originating_id)
    get_agreement(receiving_id)

    record = common_fields()
    record.update({
        "_kind": "Referral",
        "referral_code": referral_code,
        "originating_agreement_id": originating_id,
        "receiving_agreement_id": receiving_id,
        "customer_household_ref": customer_ref,
        "job_description": job_description,
        "estimated_job_value_cents": estimated_value,
        "settled_job_value_cents": None,
        "referral_fee_rate": as_number(fee_rate),
        "referral_fee_cents": 0,
        "fee_variant": None,
        "accepted_clock_iso": None,
        "expires_clock_iso": derived.iso_of(hours_from(now_dt(), REFERRAL_EXPIRY_HOURS)),
        "settled_clock_iso": None,
        "dispute_reason": None,
        "status": "PENDING",
    })
    db.referrals[record["id"]] = record
    return created(record)


@bp.get("/franchise/referrals/<referral_id>")
def read_referral(referral_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_referral(referral_id))


@bp.get("/franchise/referrals")
def list_referrals():
    uid, role = guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    rows = None
    if role == "FranchiseeOperator":
        # PRD 2.1: the entity-backed role is a party to a resource only when its
        # Franchisee id is one of the resource's Franchisee foreign keys; a
        # referral names its two parties through its two agreements.
        rows = []
        for referral in db.referrals.values():
            originating = db.agreements.get(referral.get("originating_agreement_id"))
            receiving = db.agreements.get(referral.get("receiving_agreement_id"))
            if (originating and originating.get("franchisee_id") == uid) or (
                    receiving and receiving.get("franchisee_id") == uid):
                rows.append(referral)
    return paged(db.referrals, "originating_agreement_id", "receiving_agreement_id",
                 "status", rows=rows)


@bp.post("/franchise/referrals/<referral_id>/accept")
def accept_referral(referral_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    referral = _started_referral(referral_id)
    _require_status(referral, ["PENDING"])
    require_receiving_franchisee(uid, role, _receiving_agreement(referral))
    expires = parse_instant(referral.get("expires_clock_iso") or "")
    if expires is None or not now_dt() < expires:
        raise ApiError("ERR_REFERRAL_EXPIRED")
    referral["status"] = "ACCEPTED"
    referral["accepted_clock_iso"] = derived.now_iso()
    touch(referral)
    return ok(referral)


@bp.post("/franchise/referrals/<referral_id>/decline")
def decline_referral(referral_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    referral = _started_referral(referral_id)
    _require_status(referral, ["PENDING"])
    require_receiving_franchisee(uid, role, _receiving_agreement(referral))
    referral["status"] = "DECLINED"
    touch(referral)
    return ok(referral)


@bp.post("/franchise/referrals/<referral_id>/complete")
def complete_referral(referral_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, ["settled_job_value_cents"])
    settled_value = req_int(b, "settled_job_value_cents", minimum=0)
    referral = _started_referral(referral_id)
    _require_status(referral, ["ACCEPTED"])
    receiving = _receiving_agreement(referral)
    require_receiving_franchisee(uid, role, receiving)
    referral["settled_job_value_cents"] = settled_value
    referral["status"] = "COMPLETED"
    touch(referral)
    _synthesize_work_order(referral, receiving)
    return ok(referral)


def _synthesize_work_order(referral, receiving_agreement):
    """Completion spins off the performing work (PRD 3.5)."""
    from store import common_fields as _common

    record = _common()
    record.update({
        "_kind": "WorkOrder",
        "agreement_id": receiving_agreement["id"],
        "source": "CROSS_BRAND_REFERRAL",
        "national_account_id": None,
        "lead_id": None,
        "referral_id": referral["id"],
        "priority": "STANDARD",
        "service_level_hours": 1,
        "parts_cents": 0,
        "dispatched_clock_iso": None,
        "sla_due_iso": None,
        "closed_clock_iso": None,
        "labor_cents": 0,
        "revenue_cents": 0,
        "status": "CREATED",
    })
    db.work_orders[record["id"]] = record
    return record


@bp.post("/franchise/referrals/<referral_id>/dispute")
def dispute_referral(referral_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, ["dispute_reason"])
    dispute_reason = req_str(b, "dispute_reason")
    referral = _started_referral(referral_id)
    _require_status(referral, ["COMPLETED"])
    require_referral_party(uid, role, _originating_agreement(referral),
                           _receiving_agreement(referral))
    referral["dispute_reason"] = dispute_reason
    referral["status"] = "DISPUTED"
    touch(referral)
    return ok(referral)


@bp.post("/franchise/referrals/<referral_id>/resolve-dispute")
def resolve_dispute(referral_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    referral = _started_referral(referral_id)
    _require_status(referral, ["DISPUTED"])
    referral["dispute_reason"] = None
    referral["status"] = "COMPLETED"
    touch(referral)
    return ok(referral)


@bp.post("/franchise/referrals/<referral_id>/settle")
def settle_referral(referral_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["expected_agreement_version"])
    expected_version = req_int(b, "expected_agreement_version", minimum=0)
    referral = _started_referral(referral_id)
    # PRD 3.5: a referral carrying an open dispute is refused with the specific
    # ERR_REFERRAL_DISPUTED, which is named for this condition and therefore
    # reports ahead of the generic "settle is declared from COMPLETED" gate.
    if referral.get("dispute_reason") is not None:
        raise ApiError("ERR_REFERRAL_DISPUTED")
    _require_status(referral, ["COMPLETED"])
    originating = _originating_agreement(referral)
    if expected_version != originating.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    fee, variant = referral_fee(referral)
    referral["referral_fee_cents"] = fee
    referral["fee_variant"] = variant
    referral["settled_clock_iso"] = derived.now_iso()
    referral["status"] = "SETTLED"
    touch(referral)

    receiving = _receiving_agreement(referral)
    # Post to both sides at once so the pair stays exactly opposite.
    _post_originator(originating, fee)
    _post_receiver(receiving, fee)
    return ok(referral)


def _post_originator(agreement, fee):
    if agreement is None:
        return
    derived.refresh_agreement(agreement)
    agreement["cumulative_referral_net_cents"] = (
        int(agreement.get("cumulative_referral_net_cents") or 0) + int(fee))
    touch(agreement)


def _post_receiver(agreement, fee):
    if agreement is None:
        return
    derived.refresh_agreement(agreement)
    agreement["cumulative_referral_net_cents"] = (
        int(agreement.get("cumulative_referral_net_cents") or 0) - int(fee))
    touch(agreement)