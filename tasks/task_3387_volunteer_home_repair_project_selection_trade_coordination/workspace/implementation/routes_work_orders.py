"""Trade work orders: commissioning, commercial loop, scheduling,
inspection, payment (PRD 3.7)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_int,
    opt_str, raise_err, now_iso, parse_dt, parse_date, clock_date,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_NOT_OWNER, E_FORBIDDEN,
    E_PROJECT_NOT_FOUND, E_CONTRACTOR_NOT_FOUND, E_SCOPE_ITEM_NOT_FOUND,
    E_WORK_ORDER_NOT_FOUND, E_CONTRACTOR_NOT_QUALIFIED, E_TRADE_MISMATCH,
    E_ALREADY_COVERED, E_PERMIT_REQUIRED, E_INVALID_DATE_RANGE,
    E_TRADE_WINDOW_CONFLICT, E_CONTRACTOR_DAY_CAPACITY, E_ENVELOPE_EXCEEDED,
)
from logic import (
    bump, project_items, sync_posture, get_project,
)
from cascades import suspend_contractor
from serializers import ser_work_order

bp = Blueprint("work_orders", __name__)

WO_STATUSES = ("QUOTE_REQUESTED", "QUOTED", "APPROVED", "SCHEDULED",
               "IN_PROGRESS", "PENDING_INSPECTION", "INSPECTION_FAILED",
               "INSPECTED", "INVOICED", "PAID", "CANCELLED")
STAFF_TARGETS = ("APPROVED", "IN_PROGRESS", "PENDING_INSPECTION", "PAID",
                 "CANCELLED")
PARTNER_TARGETS = ("QUOTED", "INVOICED")
STAFF_CANCELLABLE = ("QUOTE_REQUESTED", "QUOTED", "APPROVED", "SCHEDULED")


def _credentialed_for(contractor, visit_start):
    if contractor["status"] != "ACTIVE":
        return False
    start_day = visit_start.date()
    lic = parse_date(contractor["license_expires_on"])
    ins = parse_date(contractor["insurance_expires_on"])
    return lic is not None and ins is not None and lic >= start_day \
        and ins >= start_day


@bp.post("/rebuild/trade-work-orders")
def create_work_order():
    require_roles("AffiliateStaff")
    b = body()
    project_id = b.get("project_id")
    if project_id is None:
        raise_err(E_INVALID_REQUEST, 400, "project_id is required")
    project = get_or_404("projects", project_id, E_PROJECT_NOT_FOUND)
    contractor_id = b.get("contractor_id")
    if contractor_id is None:
        raise_err(E_INVALID_REQUEST, 400, "contractor_id is required")
    contractor = get_or_404("contractors", contractor_id,
                            E_CONTRACTOR_NOT_FOUND)
    item_ids = b.get("scope_item_ids")
    if not isinstance(item_ids, list) or not item_ids:
        raise_err(E_INVALID_REQUEST, 400,
                  "scope_item_ids must be a non-empty array")
    items = []
    for iid in item_ids:
        if not isinstance(iid, str):
            raise_err(E_INVALID_REQUEST, 400,
                      "scope_item_ids elements must be strings")
        item = STORES["scope_items"].get(iid)
        if item is None:
            raise_err(E_SCOPE_ITEM_NOT_FOUND, 404,
                      "scope item %s not found" % iid)
        items.append(item)
    # State gates (tier 6).
    if project["status"] not in ("PLANNING", "READY"):
        raise_err(E_INVALID_STATE, 409,
                  "project must be PLANNING or READY")
    for item in items:
        if (item["assessment_id"] != project["_assessment_id"]
                or item["status"] != "INCLUDED"):
            raise_err(E_INVALID_STATE, 409,
                      "every item must be an INCLUDED item of the project's "
                      "assessment")
    # Credentials (tier 8).
    if contractor["status"] != "ACTIVE":
        raise_err(E_CONTRACTOR_NOT_QUALIFIED, 422,
                  "contractor must be ACTIVE")
    # Constraints (tier 10).
    for item in items:
        if item["volunteer_performable"] \
                or item["required_trade"] != contractor["trade"]:
            raise_err(E_TRADE_MISMATCH, 422,
                      "covered items must be licensed-trade items matching "
                      "the contractor's trade")
    for item in items:
        for w in STORES["work_orders"].values():
            if (w["status"] != "CANCELLED"
                    and item["id"] in w["scope_item_ids"]):
                raise_err(E_ALREADY_COVERED, 409,
                          "scope item %s is already covered" % item["id"])
    rec = new_record("work_orders", {
        "project_id": project_id,
        "contractor_id": contractor_id,
        "scope_item_ids": list(item_ids),
        "trade": contractor["trade"],
        "status": "QUOTE_REQUESTED",
        "quote_cents": None,
        "invoice_cents": None,
        "permit_number": None,
        "visit_start": None,
        "visit_end": None,
        "inspected_on": None,
        "cancellation_reason": None,
    }, now_iso)
    sync_posture(project)
    return ok_obj(ser_work_order(rec), 201)


@bp.get("/rebuild/trade-work-orders")
def list_work_orders():
    require_roles("Any")
    recs = list(STORES["work_orders"].values())
    pid = request.args.get("project_id")
    if pid is not None:
        recs = [r for r in recs if r["project_id"] == pid]
    cid = request.args.get("contractor_id")
    if cid is not None:
        recs = [r for r in recs if r["contractor_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_work_order)


@bp.get("/rebuild/trade-work-orders/<workOrderId>")
def get_work_order(workOrderId):
    require_roles("Any")
    rec = get_or_404("work_orders", workOrderId, E_WORK_ORDER_NOT_FOUND)
    return ok_obj(ser_work_order(rec))


@bp.post("/rebuild/trade-work-orders/<workOrderId>/schedule")
def schedule_work_order(workOrderId):
    require_roles("AffiliateStaff")
    rec = get_or_404("work_orders", workOrderId, E_WORK_ORDER_NOT_FOUND)
    if rec["status"] != "APPROVED":
        raise_err(E_INVALID_STATE, 409,
                  "only an APPROVED work order can be scheduled")
    b = body()
    vs_raw = b.get("visit_start")
    ve_raw = b.get("visit_end")
    vs = parse_dt(vs_raw)
    ve = parse_dt(ve_raw)
    if vs is None or ve is None:
        raise_err(E_INVALID_REQUEST, 400,
                  "visit_start and visit_end must be ISO-8601 datetimes")
    contractor = STORES["contractors"].get(rec["contractor_id"])
    if contractor is None or not _credentialed_for(contractor, vs):
        raise_err(E_CONTRACTOR_NOT_QUALIFIED, 422,
                  "contractor must be ACTIVE with license and insurance "
                  "valid through the visit start date")
    if not (ve > vs):
        raise_err(E_INVALID_DATE_RANGE, 422,
                  "visit_end must be strictly after visit_start")
    # Half-open overlap: [visit_start, visit_end); adjacency permitted.
    peers = [w for w in STORES["work_orders"].values()
             if w["contractor_id"] == rec["contractor_id"]
             and w["id"] != rec["id"]
             and w["status"] in ("SCHEDULED", "IN_PROGRESS")]
    for w in peers:
        os_ = parse_dt(w["visit_start"])
        oe = parse_dt(w["visit_end"])
        if os_ is not None and oe is not None and os_ < ve and vs < oe:
            raise_err(E_TRADE_WINDOW_CONFLICT, 409,
                      "visit window overlaps another scheduled visit")
    same_day = [w for w in peers
                if parse_dt(w["visit_start"]) is not None
                and parse_dt(w["visit_start"]).date() == vs.date()]
    if len(same_day) >= contractor["max_concurrent_jobs"]:
        raise_err(E_CONTRACTOR_DAY_CAPACITY, 409,
                  "contractor is at capacity on that calendar day")
    rec["visit_start"] = vs_raw
    rec["visit_end"] = ve_raw
    rec["status"] = "SCHEDULED"
    bump(rec)
    project = get_project(rec["project_id"])
    if project is not None:
        sync_posture(project)
    return ok_obj(ser_work_order(rec))


@bp.post("/rebuild/trade-work-orders/<workOrderId>/inspect")
def inspect_work_order(workOrderId):
    require_roles("AffiliateStaff")
    rec = get_or_404("work_orders", workOrderId, E_WORK_ORDER_NOT_FOUND)
    if rec["status"] != "PENDING_INSPECTION":
        raise_err(E_INVALID_STATE, 409,
                  "only a PENDING_INSPECTION work order can be inspected")
    b = body()
    outcome = b.get("outcome")
    if outcome not in ("PASSED", "FAILED"):
        raise_err(E_INVALID_REQUEST, 400,
                  "outcome must be PASSED or FAILED")
    rec["inspected_on"] = get_clock()
    if outcome == "PASSED":
        rec["status"] = "INSPECTED"
        bump(rec)
        items_by_id = STORES["scope_items"]
        for iid in rec["scope_item_ids"]:
            item = items_by_id.get(iid)
            if item is not None and item["status"] == "INCLUDED":
                item["status"] = "COMPLETED"
        project = get_project(rec["project_id"])
        if project is not None:
            sync_posture(project)
    else:
        rec["status"] = "INSPECTION_FAILED"
        bump(rec)
        contractor = STORES["contractors"].get(rec["contractor_id"])
        if contractor is not None:
            contractor["strike_count"] += 1
            bump(contractor)
            if contractor["strike_count"] >= 3 \
                    and contractor["status"] == "ACTIVE":
                suspend_contractor(contractor)
    return ok_obj(ser_work_order(rec))


@bp.patch("/rebuild/trade-work-orders/<workOrderId>")
def patch_work_order(workOrderId):
    uid, role = require_roles("TradePartner", "AffiliateStaff")
    rec = get_or_404("work_orders", workOrderId, E_WORK_ORDER_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in WO_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(WO_STATUSES))
    # Tier 3: ownership and role-field rules.
    if role == "TradePartner":
        if rec["contractor_id"] != uid:
            raise_err(E_NOT_OWNER, 403,
                      "a TradePartner may only move its own work orders")
        if target not in PARTNER_TARGETS:
            raise_err(E_FORBIDDEN, 403,
                      "a TradePartner may only set QUOTED or INVOICED")
    else:  # AffiliateStaff
        if target in PARTNER_TARGETS:
            raise_err(E_FORBIDDEN, 403,
                      "QUOTED and INVOICED are TradePartner transitions")
    project = get_project(rec["project_id"])

    if target == "QUOTED":
        if rec["status"] != "QUOTE_REQUESTED":
            raise_err(E_INVALID_STATE, 409,
                      "work order must be QUOTE_REQUESTED")
        quote = req_int(b, "quote_cents", lo=1)
        rec["quote_cents"] = quote
        rec["status"] = "QUOTED"
    elif target == "INVOICED":
        if rec["status"] != "INSPECTED":
            raise_err(E_INVALID_STATE, 409, "work order must be INSPECTED")
        invoice = req_int(b, "invoice_cents", lo=1)
        rec["invoice_cents"] = invoice
        rec["status"] = "INVOICED"
    elif target == "APPROVED":
        if rec["status"] != "QUOTED":
            raise_err(E_INVALID_STATE, 409, "work order must be QUOTED")
        permit = opt_str(b, "permit_number", default=None)
        needs_permit = any(
            (STORES["scope_items"].get(iid) or {}).get("requires_permit")
            for iid in rec["scope_item_ids"])
        if needs_permit and not permit:
            raise_err(E_PERMIT_REQUIRED, 422,
                      "a permit_number is required when a covered item "
                      "requires a permit")
        if permit:
            rec["permit_number"] = permit
        rec["status"] = "APPROVED"
    elif target == "IN_PROGRESS":
        if rec["status"] == "SCHEDULED":
            if clock_date() < parse_date(rec["visit_start"]):
                raise_err(E_INVALID_STATE, 409,
                          "work cannot commence before the visit start date")
            rec["status"] = "IN_PROGRESS"
            bump(rec)
            if project is not None and project["status"] == "EVENT_SCHEDULED":
                project["status"] = "IN_BUILD"
                bump(project)
            return ok_obj(ser_work_order(rec))
        if rec["status"] == "INSPECTION_FAILED":
            # Rework loop, permitted only while the contractor is ACTIVE.
            contractor = STORES["contractors"].get(rec["contractor_id"])
            if contractor is None or contractor["status"] != "ACTIVE":
                raise_err(E_CONTRACTOR_NOT_QUALIFIED, 422,
                          "rework requires an ACTIVE contractor")
            rec["status"] = "IN_PROGRESS"
        else:
            raise_err(E_INVALID_STATE, 409,
                      "work order must be SCHEDULED or INSPECTION_FAILED")
    elif target == "PENDING_INSPECTION":
        if rec["status"] != "IN_PROGRESS":
            raise_err(E_INVALID_STATE, 409,
                      "work order must be IN_PROGRESS")
        rec["status"] = "PENDING_INSPECTION"
    elif target == "PAID":
        if rec["status"] != "INVOICED":
            raise_err(E_INVALID_STATE, 409, "work order must be INVOICED")
        if project is not None and \
                rec["invoice_cents"] > project["reserved_balance_cents"]:
            raise_err(E_ENVELOPE_EXCEEDED, 402,
                      "invoice exceeds the project's remaining reserve")
        rec["status"] = "PAID"
        bump(rec)
        if project is not None:
            project["reserved_balance_cents"] -= rec["invoice_cents"]
            sync_posture(project, touch=False)
            bump(project)
        return ok_obj(ser_work_order(rec))
    elif target == "CANCELLED":
        if rec["status"] not in STAFF_CANCELLABLE:
            raise_err(E_INVALID_STATE, 409,
                      "work order cannot be cancelled from %s"
                      % rec["status"])
        rec["cancellation_reason"] = opt_str(b, "cancellation_reason",
                                             default=None)
        rec["status"] = "CANCELLED"
        bump(rec)
        if project is not None:
            sync_posture(project)
        return ok_obj(ser_work_order(rec))
    bump(rec)
    return ok_obj(ser_work_order(rec))
