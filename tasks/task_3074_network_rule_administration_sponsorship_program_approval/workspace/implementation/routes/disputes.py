"""Disputes: open, list, get, evidence, decide, request-arbitration, arbitrate,
close; plus the global evidence list/get endpoints."""

from datetime import timedelta
import uuid

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, is_currency, logical_now,
    logical_now_iso, paginate, req_enum, req_int, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import ok

bp = Blueprint("disputes", __name__)

EVIDENCE_TYPES = {"TRANSACTION_RECORD", "PROOF_OF_DELIVERY", "REFUND_POLICY", "CARDHOLDER_LETTER", "OTHER"}
EVIDENCE_WINDOW_DAYS = 30
ARBITRATION_WINDOW_DAYS = 45

DISPUTE_FEE_CENTS = 1500
CASE_PROCESSING_FEE_CENTS = 500
ARBITRATION_FEE_CENTS = 25000

DISPUTE_READ_ROLES = {"NetworkOperator", "DisputeAnalyst", "Member"}


@bp.post("/network/disputes")
def open_dispute():
    user_id, _ = require_roles({"Member"})
    body = get_json()
    reason_code = req_str(body, "reason_code")
    issuer_member_id = req_str(body, "issuer_member_id")
    acquirer_member_id = req_str(body, "acquirer_member_id")
    merchant_id = req_str(body, "merchant_id")
    amount = req_int(body, "transaction_amount_cents")
    currency = req_str(body, "currency")

    # Existence, left-to-right
    exists_or_404(db.members, issuer_member_id, "issuer member")
    exists_or_404(db.members, acquirer_member_id, "acquirer member")
    merchant = exists_or_404(db.merchants, merchant_id, "merchant")

    if not is_currency(currency):
        raise_err("ERR_VALIDATION", "currency must be a 3-letter uppercase ISO 4217 code")

    if merchant["status"] != "ACTIVE":
        raise_err("ERR_MERCHANT_NOT_ACTIVE", "Referenced merchant is not ACTIVE")

    rec = base_record()
    rec.update({
        "reason_code": reason_code,
        "issuer_member_id": issuer_member_id,
        "acquirer_member_id": acquirer_member_id,
        "merchant_id": merchant_id,
        "transaction_amount_cents": amount,
        "currency": currency,
        "status": "OPENED",
        "winning_side": None,
        "filing_clock": logical_now_iso(),
        "issuer_liability_cents": 0,
        "acquirer_liability_cents": 0,
    })
    db.disputes[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/disputes")
def list_disputes():
    require_roles(DISPUTE_READ_ROLES)
    items = list(db.disputes.values())
    issuer = request.args.get("issuer_member_id")
    acquirer = request.args.get("acquirer_member_id")
    merchant_id = request.args.get("merchant_id")
    status = request.args.get("status")
    if issuer is not None:
        items = [d for d in items if d["issuer_member_id"] == issuer]
    if acquirer is not None:
        items = [d for d in items if d["acquirer_member_id"] == acquirer]
    if merchant_id is not None:
        items = [d for d in items if d["merchant_id"] == merchant_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/disputes/<did>")
def get_dispute(did):
    require_roles(DISPUTE_READ_ROLES)
    rec = get_or_404(db.disputes, did)
    return ok(rec, 200)


@bp.post("/network/disputes/<did>/evidence")
def submit_evidence(did):
    user_id, _ = require_roles({"Member"})
    rec = get_or_404(db.disputes, did)
    if user_id not in (rec["issuer_member_id"], rec["acquirer_member_id"]):
        raise_err("ERR_IDENTITY_MISMATCH", "Only a case party may submit evidence")
    if rec["status"] not in ("OPENED", "EVIDENCE_SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Dispute is not accepting evidence")
    body = get_json()
    evidence_type = req_enum(body, "evidence_type", EVIDENCE_TYPES)
    document_ref = req_str(body, "document_ref")
    now = logical_now()
    from helpers import parse_iso
    if now > parse_iso(rec["filing_clock"]) + timedelta(days=EVIDENCE_WINDOW_DAYS):
        raise_err("ERR_WINDOW_EXPIRED", "Evidence window has closed")
    ev = {
        "id": str(uuid.uuid4()),
        "created_at": logical_now_iso(),
        "dispute_case_id": did,
        "submitted_by_member_id": user_id,
        "evidence_type": evidence_type,
        "document_ref": document_ref,
        "submitted_at": logical_now_iso(),
    }
    db.evidence[ev["id"]] = ev
    if rec["status"] == "OPENED":
        rec["status"] = "EVIDENCE_SUBMITTED"
        touch(rec)
    return ok(ev, 201)


@bp.get("/network/disputes/<did>/evidence-list")
def list_dispute_evidence(did):
    require_roles(DISPUTE_READ_ROLES)
    get_or_404(db.disputes, did)
    items = [e for e in db.evidence.values() if e["dispute_case_id"] == did]
    case_id = request.args.get("dispute_case_id")
    submitted_by = request.args.get("submitted_by_member_id")
    if case_id is not None:
        items = [e for e in items if e["dispute_case_id"] == case_id]
    if submitted_by is not None:
        items = [e for e in items if e["submitted_by_member_id"] == submitted_by]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.post("/network/disputes/<did>/decide")
def decide_dispute(did):
    require_roles({"DisputeAnalyst"})
    rec = get_or_404(db.disputes, did)
    body = get_json()
    winning_side = req_enum(body, "winning_side", {"ISSUER", "ACQUIRER"})
    if rec["status"] not in ("OPENED", "EVIDENCE_SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Dispute is not in a decidable state")
    rec["winning_side"] = winning_side
    if winning_side == "ISSUER":
        rec["acquirer_liability_cents"] = rec["transaction_amount_cents"] + DISPUTE_FEE_CENTS
        rec["issuer_liability_cents"] = 0
    else:
        rec["issuer_liability_cents"] = CASE_PROCESSING_FEE_CENTS
        rec["acquirer_liability_cents"] = 0
    rec["status"] = "DECIDED"
    rec["filing_clock"] = logical_now_iso()
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/disputes/<did>/request-arbitration")
def request_arbitration(did):
    user_id, _ = require_roles({"Member"})
    rec = get_or_404(db.disputes, did)
    if user_id not in (rec["issuer_member_id"], rec["acquirer_member_id"]):
        raise_err("ERR_IDENTITY_MISMATCH", "Only a case party may request arbitration")
    if rec["status"] != "DECIDED":
        raise_err("ERR_INVALID_STATE", "Dispute is not DECIDED")
    from helpers import parse_iso
    if not (logical_now() < parse_iso(rec["filing_clock"]) + timedelta(days=ARBITRATION_WINDOW_DAYS)):
        raise_err("ERR_WINDOW_EXPIRED", "Arbitration window has closed")
    rec["status"] = "ARBITRATION_REQUESTED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/disputes/<did>/arbitrate")
def arbitrate_dispute(did):
    require_roles({"DisputeAnalyst"})
    rec = get_or_404(db.disputes, did)
    body = get_json()
    winning_side = req_enum(body, "winning_side", {"ISSUER", "ACQUIRER"})
    if rec["status"] != "ARBITRATION_REQUESTED":
        raise_err("ERR_INVALID_STATE", "Dispute is not ARBITRATION_REQUESTED")
    # Base outcome fee plus arbitration fee on the losing side
    if winning_side == "ISSUER":
        rec["acquirer_liability_cents"] = rec["transaction_amount_cents"] + DISPUTE_FEE_CENTS + ARBITRATION_FEE_CENTS
        rec["issuer_liability_cents"] = 0
    else:
        rec["issuer_liability_cents"] = CASE_PROCESSING_FEE_CENTS + ARBITRATION_FEE_CENTS
        rec["acquirer_liability_cents"] = 0
    rec["winning_side"] = winning_side
    rec["status"] = "ARBITRATION_DECIDED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/disputes/<did>/close")
def close_dispute(did):
    require_roles({"DisputeAnalyst"})
    rec = get_or_404(db.disputes, did)
    if rec["status"] not in ("DECIDED", "ARBITRATION_DECIDED"):
        raise_err("ERR_INVALID_STATE", "Dispute is not DECIDED or ARBITRATION_DECIDED")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(rec, 200)


@bp.get("/network/evidence")
def list_all_evidence():
    require_roles({"NetworkOperator", "DisputeAnalyst"})
    items = list(db.evidence.values())
    case_id = request.args.get("dispute_case_id")
    submitted_by = request.args.get("submitted_by_member_id")
    if case_id is not None:
        items = [e for e in items if e["dispute_case_id"] == case_id]
    if submitted_by is not None:
        items = [e for e in items if e["submitted_by_member_id"] == submitted_by]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/evidence/<eid>")
def get_evidence(eid):
    require_roles({"NetworkOperator", "DisputeAnalyst"})
    rec = get_or_404(db.evidence, eid)
    return ok(rec, 200)
