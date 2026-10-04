"""WorkOrder endpoints -- SLA windows and the breach cascade (PRD 3.4).

POST /franchise/work-orders, GET /franchise/work-orders[/{id}]
POST /franchise/work-orders/{id}/dispatch|start|complete|breach
"""
from flask import Blueprint

import cascades
import derived
from auth import guard, require_performing_franchisee
from config import (
    WORK_ORDER_PRIORITIES,
    WORK_ORDER_SOURCES,
)
from errors import ApiError
from fetch import get_account, get_agreement, get_lead, get_referral, get_work_order, paged
from response import created, ok
from store import common_fields, db, hours_from, now_dt, parse_instant, touch
from validate import (
    body,
    opt_id,
    opt_int,
    reject_unknown,
    req_enum,
    req_id,
    req_int,
)
from calculations import labor_charge, sla_due_hours

bp = Blueprint("work_orders", __name__)

CREATE_INPUT = [
    "agreement_id", "source", "priority", "service_level_hours", "parts_cents",
    "national_account_id", "lead_id", "referral_id",
]

PROGRAM_SOURCES = ("NATIONAL_ACCOUNT", "PROPERTY_MANAGER")


def _started_work_order(work_order_id):
    work_order = get_work_order(work_order_id)
    if work_order.get("status") in ("COMPLETED", "SLA_BREACHED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    return work_order


def _require_status(work_order, allowed):
    if work_order.get("status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


@bp.post("/franchise/work-orders")
def create_work_order():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    agreement_id = req_id(b, "agreement_id")
    source = req_enum(b, "source", WORK_ORDER_SOURCES)
    priority = req_enum(b, "priority", WORK_ORDER_PRIORITIES)
    service_level_hours = req_int(b, "service_level_hours", minimum=1)
    parts_cents = opt_int(b, "parts_cents", default=0, minimum=0)
    national_account_id = opt_id(b, "national_account_id")
    lead_id = opt_id(b, "lead_id")
    referral_id = opt_id(b, "referral_id")

    # Body foreign keys resolve in the order the input list declares them.
    get_agreement(agreement_id)
    if national_account_id is not None:
        get_account(national_account_id)
    if lead_id is not None:
        get_lead(lead_id)
    if referral_id is not None:
        get_referral(referral_id)

    # Source pins which companion references are required and which must be null.
    if source in PROGRAM_SOURCES:
        if national_account_id is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "national_account_id is required for a program work order.")
        if lead_id is not None or referral_id is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A program work order carries no lead or referral reference.")
    elif source == "CALL_CENTER_LEAD":
        if lead_id is None:
            raise ApiError("ERR_INVALID_REQUEST", "lead_id is required for a call-center lead.")
        if national_account_id is not None or referral_id is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A call-center lead work order carries no program or referral reference.")
    elif source == "CROSS_BRAND_REFERRAL":
        if referral_id is None:
            raise ApiError("ERR_INVALID_REQUEST", "referral_id is required for a cross-brand referral.")
        if national_account_id is not None or lead_id is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A cross-brand work order carries no program or lead reference.")
    else:
        if national_account_id is not None or lead_id is not None or referral_id is not None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "A direct work order carries no companion reference.")

    record = common_fields()
    record.update({
        "_kind": "WorkOrder",
        "agreement_id": agreement_id,
        "source": source,
        "national_account_id": national_account_id,
        "lead_id": lead_id,
        "referral_id": referral_id,
        "priority": priority,
        "service_level_hours": service_level_hours,
        "parts_cents": parts_cents,
        "dispatched_clock_iso": None,
        "sla_due_iso": None,
        "closed_clock_iso": None,
        "labor_cents": 0,
        "revenue_cents": 0,
        "status": "CREATED",
    })
    db.work_orders[record["id"]] = record
    return created(record)


@bp.get("/franchise/work-orders/<work_order_id>")
def read_work_order(work_order_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_work_order(work_order_id))


@bp.get("/franchise/work-orders")
def list_work_orders():
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return paged(
        db.work_orders,
        "agreement_id", "national_account_id", "lead_id", "referral_id",
        "status", "priority",
    )


@bp.post("/franchise/work-orders/<work_order_id>/dispatch")
def dispatch_work_order(work_order_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    work_order = _started_work_order(work_order_id)
    _require_status(work_order, ["CREATED"])
    agreement = get_agreement(work_order.get("agreement_id"))
    require_performing_franchisee(uid, role, agreement)

    brand = db.brands.get(agreement.get("brand_id"))
    if brand is not None and not derived.cert_at_least(
            agreement.get("certification_level"), brand.get("min_certification_level")):
        raise ApiError("ERR_CERTIFICATION_TOO_LOW")

    if work_order.get("source") in PROGRAM_SOURCES:
        account = db.national_accounts.get(work_order.get("national_account_id"))
        if account is None:
            raise ApiError("ERR_ACCOUNT_NOT_FOUND")
        if agreement.get("brand_id") not in (account.get("contracted_brands") or []):
            raise ApiError("ERR_ACCOUNT_BRAND_NOT_CONTRACTED")
        # Cross-entity linkage (rung 8) precedes the temporal window (rung 10):
        # work may only be dispatched for a program that is still ACTIVE.
        if account.get("status") != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_SUSPENDED")
        if int(work_order.get("service_level_hours") or 0) > int(account.get("service_level_hours") or 0):
            raise ApiError("ERR_SLA_WINDOW_EXCEEDS_PROGRAM")

    work_order["status"] = "DISPATCHED"
    work_order["dispatched_clock_iso"] = derived.now_iso()
    hours = sla_due_hours(work_order.get("service_level_hours"), work_order.get("priority"))
    work_order["sla_due_iso"] = derived.iso_of(hours_from(now_dt(), hours))
    touch(work_order)
    return ok(work_order)


@bp.post("/franchise/work-orders/<work_order_id>/start")
def start_work_order(work_order_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    work_order = _started_work_order(work_order_id)
    _require_status(work_order, ["DISPATCHED"])
    agreement = get_agreement(work_order.get("agreement_id"))
    require_performing_franchisee(uid, role, agreement)
    work_order["status"] = "IN_PROGRESS"
    touch(work_order)
    return ok(work_order)


@bp.post("/franchise/work-orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    uid, role = guard(["FranchiseeOperator"])
    b = body()
    reject_unknown(b, [])
    work_order = _started_work_order(work_order_id)
    _require_status(work_order, ["IN_PROGRESS"])
    agreement = get_agreement(work_order.get("agreement_id"))
    require_performing_franchisee(uid, role, agreement)

    work_order["status"] = "COMPLETED"
    work_order["closed_clock_iso"] = derived.now_iso()
    work_order["labor_cents"] = labor_charge(work_order)
    work_order["revenue_cents"] = int(work_order.get("labor_cents") or 0) + int(
        work_order.get("parts_cents") or 0)
    touch(work_order)

    account = db.national_accounts.get(work_order.get("national_account_id"))
    if account is not None:
        derived.refresh_account(account)
        account["accumulated_revenue_cents"] = int(
            account.get("accumulated_revenue_cents") or 0) + int(work_order.get("revenue_cents") or 0)
        touch(account)

    cascades.complete_referral_for_work_order(work_order)
    return ok(work_order)


@bp.post("/franchise/work-orders/<work_order_id>/breach")
def breach_work_order(work_order_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    work_order = _started_work_order(work_order_id)
    _require_status(work_order, ["IN_PROGRESS"])
    due = parse_instant(work_order.get("sla_due_iso") or "")
    if due is None or now_dt() < due:
        raise ApiError("ERR_SLA_NOT_BREACHED")

    work_order["status"] = "SLA_BREACHED"
    work_order["closed_clock_iso"] = derived.now_iso()
    work_order["labor_cents"] = labor_charge(work_order)
    work_order["revenue_cents"] = int(work_order.get("labor_cents") or 0) + int(
        work_order.get("parts_cents") or 0)
    touch(work_order)

    account = db.national_accounts.get(work_order.get("national_account_id"))
    if account is not None:
        cascades.breach_cascade(work_order, account)
    return ok(work_order)