"""Fraud: fraud cases, monitoring cycles with evaluation, remediation plans."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, logical_now, logical_now_iso,
    paginate, parse_iso, req_int, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import iso3, ok
from services.cascade import suspend_member_cascade

bp = Blueprint("fraud", __name__)

MERCHANT_FRAUD_THRESHOLD_BPS = 100
ACQUIRER_FRAUD_THRESHOLD_BPS = 50
REMEDIATION_WINDOW_DAYS = 60

READ_ROLES = {"NetworkOperator", "FraudAnalyst"}


# ---------------- Fraud cases ----------------

@bp.post("/network/fraud-cases")
def create_fraud_case():
    require_roles({"Member", "FraudAnalyst"})
    body = get_json()
    merchant_id = req_str(body, "merchant_id")
    reported_by_member_id = req_str(body, "reported_by_member_id")
    amount = req_int(body, "fraud_amount_cents")
    exists_or_404(db.merchants, merchant_id, "merchant")
    exists_or_404(db.members, reported_by_member_id, "reporting member")
    rec = base_record()
    rec.update({
        "merchant_id": merchant_id,
        "reported_by_member_id": reported_by_member_id,
        "fraud_amount_cents": amount,
        "status": "REPORTED",
        "confirmed_at": None,
    })
    db.fraud_cases[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/fraud-cases")
def list_fraud_cases():
    require_roles(READ_ROLES)
    items = list(db.fraud_cases.values())
    merchant_id = request.args.get("merchant_id")
    reported_by = request.args.get("reported_by_member_id")
    status = request.args.get("status")
    if merchant_id is not None:
        items = [f for f in items if f["merchant_id"] == merchant_id]
    if reported_by is not None:
        items = [f for f in items if f["reported_by_member_id"] == reported_by]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/fraud-cases/<fid>")
def get_fraud_case(fid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.fraud_cases, fid)
    return ok(rec, 200)


@bp.post("/network/fraud-cases/<fid>/confirm")
def confirm_fraud_case(fid):
    require_roles({"FraudAnalyst"})
    rec = get_or_404(db.fraud_cases, fid)
    if rec["status"] != "REPORTED":
        raise_err("ERR_INVALID_STATE", "FraudCase is not REPORTED")
    merchant = db.merchants.get(rec["merchant_id"])
    if merchant is None or merchant["status"] != "ACTIVE":
        raise_err("ERR_MERCHANT_NOT_ACTIVE", "Merchant is not ACTIVE")
    rec["status"] = "CONFIRMED"
    rec["confirmed_at"] = logical_now_iso()
    touch(rec)
    participant_id = merchant.get("participant_id")
    if participant_id is not None:
        participant = db.participants.get(participant_id)
        if participant is not None:
            participant["fraud_attributed_count"] += 1
            touch(participant)
    return ok(rec, 200)


@bp.post("/network/fraud-cases/<fid>/dismiss")
def dismiss_fraud_case(fid):
    require_roles({"FraudAnalyst"})
    rec = get_or_404(db.fraud_cases, fid)
    if rec["status"] != "REPORTED":
        raise_err("ERR_INVALID_STATE", "FraudCase is not REPORTED")
    rec["status"] = "DISMISSED"
    touch(rec)
    return ok(rec, 200)


# ---------------- Fraud program cycles ----------------

@bp.post("/network/fraud-program-cycles")
def create_cycle():
    require_roles({"FraudAnalyst"})
    body = get_json()
    cycle_label = req_str(body, "cycle_label")
    if "period_start" not in body:
        raise_err("ERR_INVALID_REQUEST", "period_start is required")
    if "period_end" not in body:
        raise_err("ERR_INVALID_REQUEST", "period_end is required")
    period_start = parse_iso(body["period_start"], "period_start")
    period_end = parse_iso(body["period_end"], "period_end")
    if period_end <= period_start:
        raise_err("ERR_VALIDATION", "period_end must be strictly after period_start")
    rec = base_record()
    rec.update({
        "cycle_label": cycle_label,
        "period_start": iso3(period_start),
        "period_end": iso3(period_end),
        "evaluated_at": None,
        "status": "SCHEDULED",
        "merchants_flagged": 0,
        "acquirers_flagged": 0,
    })
    db.fraud_cycles[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/fraud-program-cycles")
def list_cycles():
    require_roles(READ_ROLES)
    items = list(db.fraud_cycles.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/fraud-program-cycles/<cid>")
def get_cycle(cid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.fraud_cycles, cid)
    return ok(rec, 200)


def _confirmed_fraud_in_period(merchant_id, period_start, period_end):
    total = 0
    for f in db.fraud_cases.values():
        if f["merchant_id"] != merchant_id or f["status"] != "CONFIRMED":
            continue
        confirmed_dt = parse_iso(f["confirmed_at"])
        if period_start <= confirmed_dt < period_end:
            total += f["fraud_amount_cents"]
    return total


def _new_remediation_plan(subject_type, subject_id, cycle_id, now):
    plan = base_record()
    plan.update({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "fraud_program_cycle_id": cycle_id,
        "actions": [],
        "status": "OPEN",
        "due_at": iso3(now + timedelta(days=REMEDIATION_WINDOW_DAYS)),
        "approved_by_id": None,
        "submitted_by_id": None,
    })
    db.remediation_plans[plan["id"]] = plan
    return plan


@bp.post("/network/fraud-program-cycles/<cid>/evaluate")
def evaluate_cycle(cid):
    require_roles({"FraudAnalyst"})
    rec = get_or_404(db.fraud_cycles, cid)
    if rec["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Cycle is not SCHEDULED")
    now = logical_now()
    period_start = parse_iso(rec["period_start"])
    period_end = parse_iso(rec["period_end"])
    if now < period_end:
        raise_err("ERR_WINDOW_EXPIRED", "Logical clock has not reached period_end")

    merchants_flagged = 0
    for m in db.merchants.values():
        if m["status"] != "ACTIVE":
            continue
        fraud_sum = _confirmed_fraud_in_period(m["id"], period_start, period_end)
        denom = max(m["declared_monthly_volume_cents"], 1)
        # exact rational comparison: fraud_sum * 10000 >= 100 * denom
        if fraud_sum * 10000 >= MERCHANT_FRAUD_THRESHOLD_BPS * denom:
            m["fraud_monitoring_status"] = "REMEDIATION_REQUIRED"
            touch(m)
            _new_remediation_plan("MERCHANT", m["id"], cid, now)
            merchants_flagged += 1

    acquirers_flagged = 0
    for member in db.members.values():
        if member["member_kind"] not in ("ACQUIRER", "BOTH") or member["status"] != "ACTIVE":
            continue
        # Portfolio: direct merchants + merchants under sponsored participants,
        # any status except TERMINATED
        sponsored_participant_ids = {
            p["id"] for p in db.participants.values()
            if p["sponsor_member_id"] == member["id"]
        }
        portfolio = [
            m for m in db.merchants.values()
            if m["status"] != "TERMINATED" and (
                m.get("acquirer_member_id") == member["id"]
                or m.get("participant_id") in sponsored_participant_ids
            )
        ]
        numerator = sum(_confirmed_fraud_in_period(m["id"], period_start, period_end)
                        for m in portfolio)
        denominator = sum(m["declared_monthly_volume_cents"] for m in portfolio)
        denominator = max(denominator, 1)
        if numerator * 10000 >= ACQUIRER_FRAUD_THRESHOLD_BPS * denominator:
            _new_remediation_plan("ACQUIRER", member["id"], cid, now)
            acquirers_flagged += 1

    # Overdue sweep: OPEN/SUBMITTED plans whose due_at is in the past
    for plan in db.remediation_plans.values():
        if plan["status"] in ("OPEN", "SUBMITTED") and parse_iso(plan["due_at"]) < now:
            plan["status"] = "OVERDUE"
            touch(plan)

    rec["merchants_flagged"] = merchants_flagged
    rec["acquirers_flagged"] = acquirers_flagged
    rec["evaluated_at"] = logical_now_iso()
    rec["status"] = "COMPLETED"
    touch(rec)
    return ok(rec, 200)


@bp.get("/network/fraud-program-cycles/<cid>/remediation-plans")
def list_cycle_plans(cid):
    require_roles(READ_ROLES)
    get_or_404(db.fraud_cycles, cid)
    items = [p for p in db.remediation_plans.values() if p["fraud_program_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


# ---------------- Remediation plans ----------------

@bp.get("/network/remediation-plans")
def list_plans():
    require_roles(READ_ROLES)
    items = list(db.remediation_plans.values())
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    cycle_id = request.args.get("fraud_program_cycle_id")
    status = request.args.get("status")
    if subject_type is not None:
        items = [p for p in items if p["subject_type"] == subject_type]
    if subject_id is not None:
        items = [p for p in items if p["subject_id"] == subject_id]
    if cycle_id is not None:
        items = [p for p in items if p["fraud_program_cycle_id"] == cycle_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/remediation-plans/<pid>")
def get_plan(pid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.remediation_plans, pid)
    return ok(rec, 200)


@bp.post("/network/remediation-plans/<pid>/submit")
def submit_plan(pid):
    user_id, _ = require_roles({"FraudAnalyst"})
    rec = get_or_404(db.remediation_plans, pid)
    if rec["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Plan is not OPEN")
    if logical_now() > parse_iso(rec["due_at"]):
        raise_err("ERR_WINDOW_EXPIRED", "Plan due date has passed")
    rec["status"] = "SUBMITTED"
    rec["submitted_by_id"] = user_id
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/remediation-plans/<pid>/approve")
def approve_plan(pid):
    user_id, _ = require_roles({"FraudAnalyst"})
    rec = get_or_404(db.remediation_plans, pid)
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Plan is not SUBMITTED")
    if user_id == rec.get("submitted_by_id"):
        raise_err("ERR_SEGREGATION_OF_DUTIES", "Approver must differ from the submitter")
    rec["status"] = "APPROVED"
    rec["approved_by_id"] = user_id
    touch(rec)
    if rec["subject_type"] == "MERCHANT":
        merchant = db.merchants.get(rec["subject_id"])
        if merchant is not None:
            merchant["fraud_monitoring_status"] = "UNDER_MONITORING"
            touch(merchant)
    return ok(rec, 200)


@bp.post("/network/remediation-plans/<pid>/complete")
def complete_plan(pid):
    require_roles({"FraudAnalyst"})
    rec = get_or_404(db.remediation_plans, pid)
    if rec["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Plan is not APPROVED")
    if logical_now() > parse_iso(rec["due_at"]):
        raise_err("ERR_WINDOW_EXPIRED", "Plan due date has passed")
    rec["status"] = "COMPLETED"
    touch(rec)
    if rec["subject_type"] == "MERCHANT":
        merchant = db.merchants.get(rec["subject_id"])
        if merchant is not None:
            merchant["fraud_monitoring_status"] = "EXEMPTED"
            touch(merchant)
    return ok(rec, 200)


@bp.post("/network/remediation-plans/<pid>/escalate")
def escalate_plan(pid):
    require_roles({"FraudAnalyst"})
    rec = get_or_404(db.remediation_plans, pid)
    if rec["status"] != "OVERDUE":
        raise_err("ERR_INVALID_STATE", "Plan is not OVERDUE")
    rec["status"] = "ESCALATED"
    touch(rec)
    if rec["subject_type"] == "ACQUIRER":
        member = db.members.get(rec["subject_id"])
        if member is not None and member["status"] == "ACTIVE":
            member["status"] = "SUSPENDED"
            member["suspension_reason"] = "FRAUD_REMEDIATION_ESCALATION"
            touch(member)
            suspend_member_cascade(member["id"])
    return ok(rec, 200)
