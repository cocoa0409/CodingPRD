"""Book catalog: titles, age-band selections (committee), print orders."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, created, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_string, req_int,
    opt_bool, req_month, pagination,
)

bp = Blueprint("catalog", __name__, url_prefix="/library")


def get_title_or_404(tid):
    t = db.titles.get(tid)
    if t is None:
        raise ApiError(404, "ERR_TITLE_NOT_FOUND", "Referenced title id does not exist")
    return t


def get_selection_or_404(sid):
    s = db.selections.get(sid)
    if s is None:
        raise ApiError(404, "ERR_SELECTION_NOT_FOUND",
                       "Referenced selection id does not exist")
    return s


def get_print_order_or_404(poid):
    po = db.print_orders.get(poid)
    if po is None:
        raise ApiError(404, "ERR_PRINT_ORDER_NOT_FOUND",
                       "Referenced print order id does not exist")
    return po


# --------------------------------------------------------------------------
# Titles
# --------------------------------------------------------------------------

@bp.post("/titles")
def create_title():
    require_roles("PlatformAdmin")
    data = body()
    check_allowed(data, {"title_name", "author", "age_band",
                         "available_from_month", "available_until_month"})
    title_name = req_string(data, "title_name")
    author = req_string(data, "author")
    age_band = req_string(data, "age_band")
    if age_band not in domain.BANDS:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "age_band must be one of INFANT, TODDLER, TWO, THREE, FOUR")
    from_month = req_month(data, "available_from_month")
    until_month = req_month(data, "available_until_month")
    if until_month < from_month:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "available_until_month must not precede available_from_month")
    rec = db.base_record()
    rec.update({
        "title_name": title_name,
        "author": author,
        "age_band": age_band,
        "available_from_month": from_month,
        "available_until_month": until_month,
    })
    db.titles[rec["id"]] = rec
    return created(domain.ser_title(rec))


@bp.get("/titles/<tid>")
def get_title(tid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_title(get_title_or_404(tid)))


# --------------------------------------------------------------------------
# Age-band selections
# --------------------------------------------------------------------------

@bp.post("/selections")
def create_selection():
    uid, role = require_roles("AdvisoryCommitteeMember")
    data = body()
    check_allowed(data, {"mailing_month", "age_band", "title_id"})
    mailing_month = req_month(data, "mailing_month")
    age_band = req_string(data, "age_band")
    if age_band not in domain.BANDS:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "age_band must be one of INFANT, TODDLER, TWO, THREE, FOUR")
    title_id = req_string(data, "title_id")
    # Priority 9: not in the past.
    if mailing_month < db.logical_month():
        raise ApiError(422, "ERR_SELECTION_MONTH_PAST",
                       "Selection mailing_month is before the current logical month")
    # Priority 10: (mailing_month, age_band) uniqueness.
    for s in db.selections.values():
        if s["mailing_month"] == mailing_month and s["age_band"] == age_band:
            raise ApiError(409, "ERR_SELECTION_EXISTS",
                           "A selection already exists for this mailing_month and age_band")
    # Priority 11: FK existence, then title availability window (inclusive).
    title = db.titles.get(title_id)
    if title is None:
        raise ApiError(404, "ERR_TITLE_NOT_FOUND", "Referenced title id does not exist")
    if not (title["available_from_month"] <= mailing_month <= title["available_until_month"]):
        raise ApiError(422, "ERR_TITLE_UNAVAILABLE_MONTH",
                       "Selection month is outside the title's availability window")
    rec = db.base_record()
    rec.update({
        "mailing_month": mailing_month,
        "age_band": age_band,
        "title_id": title_id,
        "status": "PROPOSED",
        "proposed_by": uid,
        "approved_by": None,
    })
    db.selections[rec["id"]] = rec
    return created(domain.ser_selection(rec))


@bp.get("/selections/<sid>")
def get_selection(sid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_selection(get_selection_or_404(sid)))


@bp.get("/selections")
def list_selections():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_month = request.args.get("mailing_month")
    f_band = request.args.get("age_band")
    f_title = request.args.get("title_id")
    f_status = request.args.get("status")
    rows = [s for s in db.selections.values()
            if (f_month is None or s["mailing_month"] == f_month)
            and (f_band is None or s["age_band"] == f_band)
            and (f_title is None or s["title_id"] == f_title)
            and (f_status is None or s["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_selection(s) for s in page], limit, offset, total)


@bp.post("/selections/<sid>/approve")
def approve_selection(sid):
    uid, role = require_roles("AdvisoryCommitteeMember")
    data = body()
    check_allowed(data, set())
    sel = get_selection_or_404(sid)
    if sel["status"] != "PROPOSED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a PROPOSED selection can be approved")
    if uid == sel["proposed_by"]:
        raise ApiError(403, "ERR_SELF_APPROVAL_FORBIDDEN",
                       "The proposer of a selection may never be its approver")
    sel["status"] = "APPROVED"
    sel["approved_by"] = uid
    db.touch(sel)
    return ok(domain.ser_selection(sel))


@bp.post("/selections/<sid>/reopen")
def reopen_selection(sid):
    uid, role = require_roles("AdvisoryCommitteeMember")
    data = body()
    check_allowed(data, {"reason"})
    sel = get_selection_or_404(sid)
    if sel["status"] != "APPROVED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only an APPROVED selection can be reopened")
    sel["status"] = "PROPOSED"
    sel["approved_by"] = None
    db.touch(sel)
    return ok(domain.ser_selection(sel))


# --------------------------------------------------------------------------
# Print orders
# --------------------------------------------------------------------------

@bp.post("/print-orders")
def create_print_order():
    uid, role = require_roles("PublisherOps")
    data = body()
    check_allowed(data, {"selection_id", "quantity", "is_reprint"})
    selection_id = req_string(data, "selection_id")
    quantity = req_int(data, "quantity", 1)
    is_reprint = opt_bool(data, "is_reprint", False)
    sel = db.selections.get(selection_id)
    if sel is None:
        raise ApiError(404, "ERR_SELECTION_NOT_FOUND",
                       "Referenced selection id does not exist")
    # A selection already supplied (LOCKED => a CONFIRMED order exists) refuses
    # any further print order.
    if domain.confirmed_order_for_selection(selection_id) is not None:
        raise ApiError(409, "ERR_SELECTION_ALREADY_SUPPLIED",
                       "The selection already has a CONFIRMED print order")
    if sel["status"] != "APPROVED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Print orders may only be submitted for an APPROVED-or-later selection")
    rec = db.base_record()
    rec.update({
        "selection_id": selection_id,
        "quantity": quantity,
        "is_reprint": is_reprint,
        "production_month": domain.month_add(sel["mailing_month"], -1),
        "status": "SUBMITTED",
        "unit_cents": None,
        "plate_fee_cents": None,
        "total_cents": None,
    })
    db.print_orders[rec["id"]] = rec
    return created(domain.ser_print_order(rec))


@bp.get("/print-orders/<poid>")
def get_print_order(poid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_print_order(get_print_order_or_404(poid)))


@bp.get("/print-orders")
def list_print_orders():
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_sel = request.args.get("selection_id")
    f_status = request.args.get("status")
    rows = [p for p in db.print_orders.values()
            if (f_sel is None or p["selection_id"] == f_sel)
            and (f_status is None or p["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_print_order(p) for p in page], limit, offset, total)


@bp.post("/print-orders/<poid>/confirm")
def confirm_print_order(poid):
    uid, role = require_roles("PublisherOps")
    data = body()
    check_allowed(data, set())
    po = get_print_order_or_404(poid)
    sel = db.selections[po["selection_id"]]
    if po["status"] != "SUBMITTED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a SUBMITTED print order can be confirmed")
    if sel["status"] != "APPROVED":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "The referenced selection must be APPROVED to confirm")
    for o in db.print_orders.values():
        if (o["id"] != poid and o["selection_id"] == po["selection_id"]
                and o["status"] == "CONFIRMED"):
            raise ApiError(409, "ERR_SELECTION_ALREADY_SUPPLIED",
                           "The selection already has a CONFIRMED print order")
    consumed = sum(o["quantity"] for o in db.print_orders.values()
                   if o["status"] == "CONFIRMED"
                   and o["production_month"] == po["production_month"])
    if consumed + po["quantity"] > domain.PRESS_MONTHLY_CAPACITY:
        raise ApiError(409, "ERR_PRESS_CAPACITY_EXCEEDED",
                       "Confirming this order would exceed the monthly press capacity")
    # Volume pricing locked at confirm (integer cents; reprint discount rounds
    # half up to a whole cent: round_half_up(tier * 9 / 10)).
    q = po["quantity"]
    if q >= 50000:
        unit = 140
    elif q >= 20000:
        unit = 160
    elif q >= 5000:
        unit = 185
    else:
        unit = 210
    if po["is_reprint"]:
        unit = (unit * 9 + 5) // 10
    plate = 0 if (q >= 20000 or po["is_reprint"]) else 25000
    po["unit_cents"] = unit
    po["plate_fee_cents"] = plate
    po["total_cents"] = q * unit + plate
    po["status"] = "CONFIRMED"
    db.touch(po)
    sel["status"] = "LOCKED"
    db.touch(sel)
    return ok(domain.ser_print_order(po))
