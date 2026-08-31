"""Permit applications, filings and agency decisions."""
from datetime import timedelta

from flask import Blueprint

import calc
import derive
from core import fail, new_record, ordered, parse_dt, respond_list, respond_object, store, touch
from guards import Body, auth, body, fk, must_exist, pagination, paginate, q_enum, q_str

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ["ROAD_CLOSURE", "CRANE_PLACEMENT", "OVERSIZE_ESCORT"]
PERMIT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "SUSPENDED", "VOIDED"]
DECISIONS = ["APPROVE", "DENY"]


@bp.post("/permits")
def create_permit():
    auth(["Dispatcher"])
    b = Body(body())
    lift_plan_id = b.string("lift_plan_id")
    permit_type = b.enum("permit_type", PERMIT_TYPES)
    jurisdiction_code = b.string("jurisdiction_code")
    plan = fk("lift_plans", lift_plan_id)

    escort_required = bool(plan["escort_required"])
    lead_days, fee_cents = calc.permit_fee_and_lead_days(permit_type, escort_required)
    rec = new_record({
        "lift_plan_id": lift_plan_id,
        "permit_type": permit_type,
        "jurisdiction_code": jurisdiction_code,
        "escort_required": escort_required,
        "required_lead_days": lead_days,
        "permit_fee_cents": fee_cents,
        "cancellation_fee_cents": 0,
        "submitted_at": None,
        "decision_at": None,
        "agency_reference": None,
        "denial_reason": None,
        "status": "DRAFT",
    })
    store.permits[rec["id"]] = rec
    return respond_object(derive.permit_json(rec), 201)


@bp.get("/permits/<pid>")
def read_permit(pid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager", "BillingClerk"])
    rec = must_exist("permits", pid)
    return respond_object(derive.permit_json(rec))


@bp.get("/permits")
def list_permits():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager", "BillingClerk"])
    limit, offset = pagination()
    lift_plan_id = q_str("lift_plan_id")
    status = q_enum("status", PERMIT_STATUSES)
    rows = ordered(store.permits)
    if lift_plan_id:
        rows = [r for r in rows if r["lift_plan_id"] == lift_plan_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.permit_json)
    return respond_list(items, limit, offset, total)


@bp.post("/permits/<pid>/submit")
def submit_permit(pid):
    auth(["Dispatcher"])
    permit = must_exist("permits", pid)

    if permit["status"] not in ("DRAFT", "DENIED", "SUSPENDED"):
        fail("ERR_INVALID_PERMIT_STATE",
             "Only a draft, denied or suspended application may be filed.")

    plan = store.lift_plans.get(permit["lift_plan_id"])
    site = store.sites.get(plan["site_id"]) if plan else None
    if site is not None and permit["jurisdiction_code"] != site["jurisdiction_code"]:
        fail("ERR_JURISDICTION_MISMATCH",
             "The application is addressed to a different jurisdiction than the site's.")

    window_start = parse_dt(plan["window_start"]) if plan else None
    if window_start is not None:
        required = timedelta(hours=24 * permit["required_lead_days"])
        if window_start - store.now < required:
            fail("ERR_PERMIT_LEAD_TIME_SHORT",
                 "The filing does not leave the required lead time before the lift window.")

    was_denied = permit["status"] == "DENIED"
    permit["status"] = "SUBMITTED"
    permit["submitted_at"] = store.now_iso()
    if was_denied:
        permit["denial_reason"] = None
    touch(permit)
    return respond_object(derive.permit_json(permit))


@bp.post("/permits/<pid>/record-decision")
def record_permit_decision(pid):
    auth(["Dispatcher"])
    permit = must_exist("permits", pid)
    b = Body(body())
    decision = b.enum("decision", DECISIONS)
    agency_reference = b.string("agency_reference", required=False, default=None, allow_empty=True)
    reason = b.string("reason", required=False, default=None, allow_empty=True)

    if permit["status"] != "SUBMITTED":
        fail("ERR_INVALID_PERMIT_STATE", "Only a SUBMITTED application carries a decision.")

    permit["decision_at"] = store.now_iso()
    if decision == "APPROVE":
        permit["status"] = "APPROVED"
        permit["agency_reference"] = agency_reference
    else:
        permit["status"] = "DENIED"
        permit["denial_reason"] = reason
        if agency_reference is not None:
            permit["agency_reference"] = agency_reference
    touch(permit)
    return respond_object(derive.permit_json(permit))
