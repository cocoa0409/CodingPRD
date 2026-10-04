"""Verification commerce: request creation with the pinned guard chain and
fee quote, payment, and fulfillment with privacy/record gates (PRD §3.7).
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
from auth import (
    ROLE_CLEARINGHOUSE_OPS,
    ROLE_LEARNER,
    ROLE_REQUESTER,
    authenticate,
    require_role,
)
from core import (
    ERR_CONSENT_REQUIRED,
    ERR_DUPLICATE_REQUEST,
    ERR_INSUFFICIENT_CREDIT,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INSTITUTION_SUSPENDED,
    ERR_INVALID_STATE,
    ERR_MAX_ACTIVE_TRANSCRIPTS,
    ERR_PRIVACY_BLOCKED,
    ERR_PURPOSE_NOT_PERMITTED,
    ERR_QUOTE_EXPIRED,
    ERR_REQUEST_NOT_FOUND,
    ERR_REQUESTER_NOT_VETTED,
    ERR_STUDENT_NOT_FOUND,
    ERR_UNAUTHORIZED,
    get_body,
    list_response,
    ok_object,
    opt_bool,
    raise_err,
    req_enum,
    req_str,
)

bp = Blueprint("verification", __name__)

PRODUCTS = ("DEGREE", "ENROLLMENT", "TRANSCRIPT")
PURPOSES = ("EMPLOYMENT", "BACKGROUND_SCREEN", "LOAN_DEFERMENT", "INSURANCE", "SELF")
KIND_PURPOSES = {
    "EMPLOYER": ("EMPLOYMENT", "INSURANCE"),
    "BACKGROUND_SCREENER": ("EMPLOYMENT", "BACKGROUND_SCREEN"),
}


def _get_request(rid):
    r = db.store.requests.get(rid)
    if r is None:
        raise_err(ERR_REQUEST_NOT_FOUND, "verification request not found")
    return r


def _refund(r):
    """Full refund: refund_cents := fee_cents credited back (no-op fee 0)."""
    r["refund_cents"] = r["fee_cents"]
    if r["requester_id"]:
        requester = db.store.requesters.get(r["requester_id"])
        if requester is not None:
            requester["credit_balance_cents"] += r["refund_cents"]
            db.touch(requester)


@bp.route("/verification-requests", methods=["POST"])
def create_request():
    caller = authenticate()
    require_role(caller, ROLE_REQUESTER, ROLE_LEARNER)
    data = get_body()

    # Ownership (priority 3) precedes standing, purpose matrix, and payload.
    if caller.role == ROLE_REQUESTER:
        rid = data.get("requester_id")
        if not isinstance(rid, str) or rid != caller.user_id:
            raise_err(ERR_UNAUTHORIZED, "requester_id must equal X-User-ID")
        requester_id = rid
    else:  # Learner self-order: no requester_id, student_id == X-User-ID
        if data.get("requester_id") is not None:
            raise_err(ERR_UNAUTHORIZED, "Learner self-orders present no requester_id")
        sid = data.get("student_id")
        if not isinstance(sid, str) or sid != caller.user_id:
            raise_err(ERR_UNAUTHORIZED, "student_id must equal X-User-ID")
        requester_id = None

    # Requester standing (priority 5).
    if caller.role == ROLE_REQUESTER and caller.entity["status"] != "VETTED":
        raise_err(ERR_REQUESTER_NOT_VETTED, "requester account is not VETTED")

    # Purpose matrix (priority 6) — evaluated only when product/purpose are
    # well-formed enum members; malformed values fall through to priority 7.
    raw_product = data.get("product_type")
    raw_purpose = data.get("purpose")
    if (
        isinstance(raw_product, str)
        and raw_product in PRODUCTS
        and isinstance(raw_purpose, str)
        and raw_purpose in PURPOSES
    ):
        if caller.role == ROLE_LEARNER:
            if not (raw_product == "TRANSCRIPT" and raw_purpose == "SELF"):
                raise_err(ERR_PURPOSE_NOT_PERMITTED, "TRANSCRIPT/SELF is Learner-only")
        else:
            if raw_product not in ("DEGREE", "ENROLLMENT"):
                raise_err(ERR_PURPOSE_NOT_PERMITTED, "DEGREE/ENROLLMENT are Requester-only")
            allowed = KIND_PURPOSES[caller.entity["requester_kind"]]
            if raw_purpose not in allowed:
                raise_err(ERR_PURPOSE_NOT_PERMITTED, "purpose not permitted for requester kind")

    # Payload well-formedness (priority 7).
    institution_id = req_str(data, "institution_id")
    student_id = req_str(data, "student_id")
    product = req_enum(data, "product_type", PRODUCTS)
    purpose = req_enum(data, "purpose", PURPOSES)
    consent = opt_bool(data, "consent_artifact", False)
    rush = opt_bool(data, "rush", False)

    # Existence (priorities 8, 10): institution first, then student (PRD §3.7).
    inst = db.store.institutions.get(institution_id)
    if inst is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    if db.store.students.get(student_id) is None:
        raise_err(ERR_STUDENT_NOT_FOUND, "student not found")

    # Institution state (priority 21).
    if inst["status"] != "ACTIVE":
        raise_err(ERR_INSTITUTION_SUSPENDED, "institution is suspended")

    now = db.now()
    is_self_transcript = caller.role == ROLE_LEARNER and product == "TRANSCRIPT"

    # Creation-time privacy gate (priority 26).
    if not is_self_transcript and calc.has_active_directive(student_id, "FULL_BLOCK", now):
        raise_err(ERR_PRIVACY_BLOCKED, "an active FULL_BLOCK covers the student")
    if product == "DEGREE" and calc.has_active_directive(student_id, "DIRECTORY_BLOCK", now):
        raise_err(ERR_PRIVACY_BLOCKED, "an active DIRECTORY_BLOCK blocks DEGREE")

    # Consent gate (priority 27).
    if product == "ENROLLMENT":
        if purpose in ("EMPLOYMENT", "BACKGROUND_SCREEN") and consent is not True:
            raise_err(ERR_CONSENT_REQUIRED, "consent_artifact is required for this purpose")
        if calc.has_active_directive(student_id, "DIRECTORY_BLOCK", now) and consent is not True:
            raise_err(ERR_CONSENT_REQUIRED, "DIRECTORY_BLOCK + ENROLLMENT requires consent_artifact")

    # Duplicate suppression (priority 33) — DEGREE/ENROLLMENT only.
    if product in ("DEGREE", "ENROLLMENT"):
        key = (requester_id, student_id, institution_id, product, purpose)
        for r in db.store.requests.values():
            if r["status"] in ("QUOTED", "PAID") and (
                r["requester_id"],
                r["student_id"],
                r["institution_id"],
                r["product_type"],
                r["purpose"],
            ) == key:
                raise_err(ERR_DUPLICATE_REQUEST, "an in-flight request with the same key exists")

    # Active-transcript cap (priority 36).
    if is_self_transcript:
        active = [
            r
            for r in db.store.requests.values()
            if r["student_id"] == caller.user_id
            and r["requester_id"] is None
            and r["product_type"] == "TRANSCRIPT"
            and r["status"] in ("QUOTED", "PAID")
        ]
        if len(active) >= calc.MAX_ACTIVE_TRANSCRIPTS:
            raise_err(ERR_MAX_ACTIVE_TRANSCRIPTS, "at most 2 active TRANSCRIPT requests per learner")

    # Fee quote — pinned for the life of the request (PRD §3.7).
    tier = calc.volume_tier(requester_id, now) if requester_id else "STANDARD"
    fee = calc.fee_quote(product, tier, rush)
    r = db.new_entity(
        {
            "requester_id": requester_id,
            "student_id": student_id,
            "institution_id": institution_id,
            "product_type": product,
            "purpose": purpose,
            "consent_artifact": consent,
            "rush": rush,
            "status": "QUOTED",
            "fee_cents": fee,
            "volume_tier_at_quote": tier,
            "quote_expires_at": now + timedelta(hours=calc.QUOTE_TTL_HOURS),
            "paid_at": None,
            "released_at": None,
            "result_status": "NONE",
            "enrollment_status_at_release": "NONE",
            "artifact_expires_at": None,
            "refund_cents": 0,
        }
    )
    db.store.requests[r["id"]] = r
    return ok_object(db.serialize(r), 201)


def _check_read_access(caller, r):
    if caller.role == ROLE_REQUESTER and r["requester_id"] != caller.user_id:
        raise_err(ERR_UNAUTHORIZED, "a requester acts only on its own requests")
    if caller.role == ROLE_LEARNER and (r["student_id"] != caller.user_id or r["requester_id"] is not None):
        raise_err(ERR_UNAUTHORIZED, "a learner acts only on its own requests")


@bp.route("/verification-requests/<rid>", methods=["GET"])
def get_request(rid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS, ROLE_REQUESTER, ROLE_LEARNER)
    r = _get_request(rid)
    _check_read_access(caller, r)
    return ok_object(db.serialize(r))


@bp.route("/verification-requests", methods=["GET"])
def list_requests():
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS, ROLE_REQUESTER, ROLE_LEARNER)
    q = request.args
    items = list(db.store.requests.values())
    if caller.role == ROLE_REQUESTER:
        items = [r for r in items if r["requester_id"] == caller.user_id]
    elif caller.role == ROLE_LEARNER:
        items = [r for r in items if r["requester_id"] is None and r["student_id"] == caller.user_id]
    if q.get("requester_id") is not None:
        items = [r for r in items if r["requester_id"] == q["requester_id"]]
    if q.get("student_id") is not None:
        items = [r for r in items if r["student_id"] == q["student_id"]]
    if q.get("institution_id") is not None:
        items = [r for r in items if r["institution_id"] == q["institution_id"]]
    if q.get("status") is not None:
        items = [r for r in items if r["status"] == q["status"]]
    return list_response(db.sorted_created(items), db.serialize)


@bp.route("/verification-requests/<rid>/pay", methods=["POST"])
def pay_request(rid):
    caller = authenticate()
    require_role(caller, ROLE_REQUESTER, ROLE_LEARNER)
    r = _get_request(rid)
    _check_read_access(caller, r)
    if r["status"] == "EXPIRED":
        raise_err(ERR_QUOTE_EXPIRED, "the quote has expired")
    if r["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "only a QUOTED request can be paid")
    if db.now() >= r["quote_expires_at"]:
        raise_err(ERR_QUOTE_EXPIRED, "the quote has expired")
    if r["requester_id"]:
        requester = db.store.requesters.get(r["requester_id"])
        if requester is None or requester["credit_balance_cents"] < r["fee_cents"]:
            raise_err(ERR_INSUFFICIENT_CREDIT, "credit balance below fee_cents")
        requester["credit_balance_cents"] -= r["fee_cents"]
        db.touch(requester)
    r["paid_at"] = db.now()
    r["status"] = "PAID"
    db.touch(r)
    return ok_object(db.serialize(r))


@bp.route("/verification-requests/<rid>/fulfill", methods=["POST"])
def fulfill_request(rid):
    caller = authenticate()
    require_role(caller, ROLE_CLEARINGHOUSE_OPS)
    r = _get_request(rid)
    if r["status"] != "PAID":
        raise_err(ERR_INVALID_STATE, "only a PAID request can be fulfilled")

    now = db.now()
    student_id = r["student_id"]
    is_self_transcript = r["product_type"] == "TRANSCRIPT" and r["requester_id"] is None

    # Gate 1: privacy (PRD §3.7).
    privacy_failed = False
    if not is_self_transcript and calc.has_active_directive(student_id, "FULL_BLOCK", now):
        privacy_failed = True
    if r["product_type"] == "DEGREE" and calc.has_active_directive(student_id, "DIRECTORY_BLOCK", now):
        privacy_failed = True
    if (
        r["product_type"] == "ENROLLMENT"
        and calc.has_active_directive(student_id, "DIRECTORY_BLOCK", now)
        and r["consent_artifact"] is not True
    ):
        privacy_failed = True
    if privacy_failed:
        _refund(r)
        r["status"] = "BLOCKED_PRIVACY"
        db.touch(r)
        return ok_object(db.serialize(r))

    # Gate 2: records.
    if r["product_type"] == "DEGREE":
        record_ok = any(
            d["student_id"] == student_id
            and d["institution_id"] == r["institution_id"]
            and d["status"] == "SEALED"
            for d in db.store.degrees.values()
        )
    elif r["product_type"] == "ENROLLMENT":
        record_ok = any(
            e["student_id"] == student_id
            and e["institution_id"] == r["institution_id"]
            and e["entry_status"] == "ACCEPTED"
            for e in db.store.entries.values()
        )
    else:  # TRANSCRIPT: either a sealed degree or an accepted entry
        record_ok = any(
            d["student_id"] == student_id
            and d["institution_id"] == r["institution_id"]
            and d["status"] == "SEALED"
            for d in db.store.degrees.values()
        ) or any(
            e["student_id"] == student_id
            and e["institution_id"] == r["institution_id"]
            and e["entry_status"] == "ACCEPTED"
            for e in db.store.entries.values()
        )
    if not record_ok:
        _refund(r)
        r["status"] = "NO_RECORD"
        db.touch(r)
        return ok_object(db.serialize(r))

    r["status"] = "RELEASED"
    r["released_at"] = now
    r["result_status"] = "VERIFIED"
    if r["product_type"] == "ENROLLMENT":
        # Recomputed as-of the fulfill date (as_of_report variant, PRD §3.7)
        # from the student's latest ACCEPTED entry at the institution.
        entries = [
            e
            for e in db.store.entries.values()
            if e["student_id"] == student_id
            and e["institution_id"] == r["institution_id"]
            and e["entry_status"] == "ACCEPTED"
        ]
        entries.sort(key=lambda e: (e["term_start"], e["_seq"]))
        latest = entries[-1]
        r["enrollment_status_at_release"] = calc.report_status(
            latest["withdrawal_date"],
            now,
            latest["career_level"],
            Decimal(str(latest["credit_hours"])),
        )
    if r["product_type"] == "TRANSCRIPT":
        r["artifact_expires_at"] = now + timedelta(hours=calc.ARTIFACT_TTL_HOURS)
    db.touch(r)
    return ok_object(db.serialize(r))
