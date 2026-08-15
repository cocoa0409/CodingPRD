"""Work order dispatch, completion cascade, verification/rework loop (PRD 3.3, 3.4)."""
from flask import Blueprint, request

from clock import CLOCK
from db import db, new_entity, sorted_items
from errors import (
    raise_error,
    ERR_ALREADY_TERMINAL,
    ERR_HOME_VISIT_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SERVICE_REQUEST_NOT_FOUND,
    ERR_TRADE_CAPACITY_EXCEEDED,
    ERR_TRADE_PARTNER_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
)
from middleware import get_caller, require_role
from response import success_list, success_object
from services.calc import chargeback_amount
from services.reserve import (
    nonvoid_chargeback_for_work_order,
    post_entry,
    recompute_partner_open_count,
    recompute_partner_outstanding,
    recompute_request_cost,
    refresh_chargeback_amounts,
    reserve_for_home,
    touch,
)
from util import serialize
from validate import (
    apply_page,
    get_body,
    pagination_params,
    req_datetime,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("work_orders", __name__)

DEFECT_RESPONSIBILITIES = {"SUBCONTRACTOR", "BUILDER", "HOMEOWNER"}
VERIFY_OUTCOMES = {"ACCEPT", "REJECT"}
WO_TERMINAL = {"ACCEPTED", "CANCELLED"}
READ_ROLES = {"WarrantyManager", "WarrantyRep", "TradePartner", "Homeowner"}


def _get_work_order_or_404(rid):
    wo = db["work_orders"].get(rid)
    if wo is None:
        raise_error(ERR_WORK_ORDER_NOT_FOUND, f"work order id does not resolve: {rid}")
    return wo


def _whole_minutes(window_start, window_end) -> int:
    return int((window_end - window_start).total_seconds() // 60)


def _validate_window(partner, home_id, window_start, window_end, exclude_wo_id=None):
    """The three scheduling guards, in order (PRD 3.3), after shape/state checks.

    1. not-in-past: window_start strictly before the clock is rejected (exactly now OK)
    2. trade daily capacity: SCHEDULED minutes on the new window's UTC date plus the
       new duration must not exceed daily_capacity_minutes (exactly at capacity OK)
    3. home visit overlap: half-open interval overlap with a SCHEDULED visit at the
       same home (back-to-back windows that merely touch are allowed)
    """
    if window_start < CLOCK.now():
        raise_error(ERR_INVALID_WINDOW, "window_start is strictly before the current clock")
    duration = _whole_minutes(window_start, window_end)
    day = window_start.date()
    used = 0
    for other in db["work_orders"].values():
        if (other["id"] != exclude_wo_id
                and other["trade_partner_id"] == partner["id"]
                and other["status"] == "SCHEDULED"
                and other["window_start"].date() == day):
            used += other["duration_minutes"]
    if used + duration > partner["daily_capacity_minutes"]:
        raise_error(ERR_TRADE_CAPACITY_EXCEEDED,
                    "partner's SCHEDULED minutes for that UTC day plus the new duration "
                    "exceed daily_capacity_minutes")
    for other in db["work_orders"].values():
        if other["id"] == exclude_wo_id or other["status"] != "SCHEDULED":
            continue
        other_sr = db["service_requests"].get(other["service_request_id"])
        if other_sr is None or other_sr["home_id"] != home_id:
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            raise_error(ERR_HOME_VISIT_OVERLAP,
                        "new window overlaps an existing SCHEDULED work order at the same home")
    return duration


@bp.post("/work-orders")
def create_work_order():
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    body = get_body()
    # Identifier resolution (precedence 4), left to right: service request, then partner.
    sr_ref = body.get("service_request_id")
    sr = db["service_requests"].get(sr_ref) if isinstance(sr_ref, str) else None
    if isinstance(sr_ref, str) and sr_ref.strip() != "" and sr is None:
        raise_error(ERR_SERVICE_REQUEST_NOT_FOUND,
                    f"service request id does not resolve: {sr_ref}")
    tp_ref = body.get("trade_partner_id")
    tp = db["trade_partners"].get(tp_ref) if isinstance(tp_ref, str) else None
    if isinstance(tp_ref, str) and tp_ref.strip() != "" and tp is None:
        raise_error(ERR_TRADE_PARTNER_NOT_FOUND,
                    f"trade partner id does not resolve: {tp_ref}")
    # Shape (precedence 5).
    req_str(body, "service_request_id")
    req_str(body, "trade_partner_id")
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise_error(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    estimated_cost_cents = req_int(body, "estimated_cost_cents", non_negative=True)
    defect_responsibility = req_enum(body, "defect_responsibility", DEFECT_RESPONSIBILITIES)
    # State legality (precedence 6): dispatch requires an APPROVED request.
    if sr["status"] == "CLOSED":
        raise_error(ERR_ALREADY_TERMINAL, "service request is CLOSED")
    if sr["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE,
                    f"dispatch is not defined from request status {sr['status']}")
    duration = _validate_window(tp, sr["home_id"], window_start, window_end)

    wo = new_entity()
    wo.update({
        "service_request_id": sr["id"],
        "trade_partner_id": tp["id"],
        "window_start": window_start,
        "window_end": window_end,
        "duration_minutes": duration,
        "estimated_cost_cents": estimated_cost_cents,
        "defect_responsibility": defect_responsibility,
        "actual_cost_cents": None,
        "status": "SCHEDULED",
        "completed_at": None,
        "rejection_reason": None,
    })
    db["work_orders"][wo["id"]] = wo
    # Dispatch re-enters the partner's SCHEDULED-count accounting and moves the
    # parent request APPROVED -> IN_SERVICE on first dispatch.
    recompute_partner_open_count(tp)
    touch(tp)
    sr["status"] = "IN_SERVICE"
    touch(sr)
    return success_object(serialize(wo), 201)


@bp.get("/work-orders/<rid>")
def fetch_work_order(rid):
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    return success_object(serialize(_get_work_order_or_404(rid)))


@bp.get("/work-orders")
def list_work_orders():
    _uid, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    service_request_id = request.args.get("service_request_id")
    trade_partner_id = request.args.get("trade_partner_id")
    status = request.args.get("status")
    items = sorted_items("work_orders")
    if service_request_id is not None:
        items = [w for w in items if w["service_request_id"] == service_request_id]
    if trade_partner_id is not None:
        items = [w for w in items if w["trade_partner_id"] == trade_partner_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = apply_page(items, limit, offset)
    return success_list([serialize(w) for w in page], total, limit, offset)


@bp.post("/work-orders/<rid>/complete")
def complete_work_order(rid):
    uid, role = get_caller()
    require_role(role, {"TradePartner"})
    wo = db["work_orders"].get(rid)
    # Ownership (precedence 3): completion belongs to the dispatched partner only.
    if wo is not None and wo["trade_partner_id"] != uid:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "a trade partner may complete only its own dispatched work orders")
    if wo is None:
        raise_error(ERR_WORK_ORDER_NOT_FOUND, f"work order id does not resolve: {rid}")
    body = get_body()
    actual_cost_cents = req_int(body, "actual_cost_cents", non_negative=True)
    if wo["status"] in WO_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"work order is {wo['status']}")
    if wo["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"complete is not defined from status {wo['status']}")

    now = CLOCK.now()
    wo["status"] = "COMPLETED"
    wo["actual_cost_cents"] = actual_cost_cents
    wo["completed_at"] = now
    touch(wo)
    # Leaving SCHEDULED drops the partner's computed open-visit count.
    partner = db["trade_partners"][wo["trade_partner_id"]]
    recompute_partner_open_count(partner)

    sr = db["service_requests"][wo["service_request_id"]]
    # CASCADE L2: request cost roll-up over COMPLETED/ACCEPTED work orders.
    recompute_request_cost(sr)
    touch(sr)
    # CASCADE L3: reserve DRAW of negative the invoiced cost (append-only ledger).
    reserve = reserve_for_home(sr["home_id"])
    if reserve is not None:
        post_entry(reserve, "DRAW", -actual_cost_cents, work_order_ref=wo["id"])
    # CASCADE L4: a linked still-provisional chargeback in ISSUED/CONTESTED is
    # refinalized against the invoiced cost; a zero final amount auto-voids it.
    cb = nonvoid_chargeback_for_work_order(wo["id"])
    if cb is not None and cb["amount_basis"] == "PROVISIONAL" and cb["status"] in ("ISSUED", "CONTESTED"):
        final = chargeback_amount(actual_cost_cents)
        cb["final_amount_cents"] = final
        cb["amount_basis"] = "FINAL"
        if final == 0:
            cb["status"] = "VOID"
        refresh_chargeback_amounts(cb)
        touch(cb)
        recompute_partner_outstanding(partner)
    touch(partner)
    return success_object(serialize(wo))


@bp.post("/work-orders/<rid>/verify")
def verify_work_order(rid):
    uid, role = get_caller()
    require_role(role, {"Homeowner"})
    wo = db["work_orders"].get(rid)
    # Ownership (precedence 3): verification belongs to the homeowner whose home
    # was serviced (through the parent request's home).
    if wo is not None:
        sr = db["service_requests"].get(wo["service_request_id"])
        home = db["homes"].get(sr["home_id"]) if sr is not None else None
        if home is not None and home["homeowner_id"] != uid:
            raise_error(ERR_NOT_RESOURCE_OWNER,
                        "a homeowner may verify only work orders of their own home")
    if wo is None:
        raise_error(ERR_WORK_ORDER_NOT_FOUND, f"work order id does not resolve: {rid}")
    sr = db["service_requests"][wo["service_request_id"]]
    body = get_body()
    outcome = req_enum(body, "outcome", VERIFY_OUTCOMES)
    rejection_reason = None
    if outcome == "REJECT":
        rejection_reason = req_str(body, "rejection_reason")
    if wo["status"] in WO_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"work order is {wo['status']}")
    if wo["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE,
                    f"verify is not defined from status {wo['status']}")

    if outcome == "ACCEPT":
        wo["status"] = "ACCEPTED"
        touch(wo)
        # Bubble-up: every sibling ACCEPTED/CANCELLED with at least one ACCEPTED
        # advances the request IN_SERVICE -> PENDING_FOLLOWUP.
        siblings = [w for w in db["work_orders"].values()
                    if w["service_request_id"] == sr["id"]]
        if (all(w["status"] in ("ACCEPTED", "CANCELLED") for w in siblings)
                and any(w["status"] == "ACCEPTED" for w in siblings)
                and sr["status"] == "IN_SERVICE"):
            now = CLOCK.now()
            sr["status"] = "PENDING_FOLLOWUP"
            sr["followup_entered_at"] = now
            # Completion SLA: entering follow-up strictly after the due instant
            # breaches; exactly AT the deadline is met.
            if sr["completion_due_at"] is not None and now > sr["completion_due_at"]:
                sr["completion_breached"] = True
                sr["escalation_level"] = 2
            touch(sr)
    else:
        wo["status"] = "REJECTED"
        wo["rejection_reason"] = rejection_reason
        touch(wo)
        # Leaving COMPLETED drops this visit's cost out of the request roll-up
        # (the roll-up counts only COMPLETED and ACCEPTED work orders).
        recompute_request_cost(sr)
        touch(sr)
    return success_object(serialize(wo))


@bp.post("/work-orders/<rid>/reschedule")
def reschedule_work_order(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    wo = _get_work_order_or_404(rid)
    body = get_body()
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    if window_end <= window_start:
        raise_error(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")
    if wo["status"] in WO_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"work order is {wo['status']}")
    if wo["status"] not in ("SCHEDULED", "REJECTED"):
        raise_error(ERR_INVALID_STATE,
                    f"reschedule is not defined from status {wo['status']}")
    sr = db["service_requests"][wo["service_request_id"]]
    partner = db["trade_partners"][wo["trade_partner_id"]]
    duration = _validate_window(partner, sr["home_id"], window_start, window_end,
                                exclude_wo_id=wo["id"])

    previous_status = wo["status"]
    wo["window_start"] = window_start
    wo["window_end"] = window_end
    wo["duration_minutes"] = duration
    if previous_status == "REJECTED":
        # Rework loop: re-entering SCHEDULED re-enters capacity accounting and the
        # retained actual_cost_cents drops out of the request roll-up until the
        # visit completes again. The earlier reserve DRAW is NOT reversed.
        wo["status"] = "SCHEDULED"
        wo["completed_at"] = None
        recompute_partner_open_count(partner)
        touch(partner)
        recompute_request_cost(sr)
        touch(sr)
    touch(wo)
    return success_object(serialize(wo))


@bp.post("/work-orders/<rid>/cancel")
def cancel_work_order(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyRep"})
    wo = _get_work_order_or_404(rid)
    get_body()
    if wo["status"] in WO_TERMINAL:
        raise_error(ERR_ALREADY_TERMINAL, f"work order is {wo['status']}")
    if wo["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"cancel is not defined from status {wo['status']}")
    wo["status"] = "CANCELLED"
    touch(wo)
    partner = db["trade_partners"][wo["trade_partner_id"]]
    recompute_partner_open_count(partner)
    # A linked provisional chargeback still in ISSUED auto-voids.
    cb = nonvoid_chargeback_for_work_order(wo["id"])
    if cb is not None and cb["status"] == "ISSUED" and cb["amount_basis"] == "PROVISIONAL":
        cb["status"] = "VOID"
        refresh_chargeback_amounts(cb)
        touch(cb)
        recompute_partner_outstanding(partner)
    touch(partner)
    return success_object(serialize(wo))
