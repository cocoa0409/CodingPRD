"""LaborCall endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES, LABOR_DEPARTMENTS, UNION_CANCEL_NOTICE_HOURS, LATE_CANCEL_FEE_PCT
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import calc
import helpers as H
import ticks

bp = Blueprint("labor", __name__)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls", methods=["POST"])
@require_roles("LaborSteward")
def create_call(tourId, engagementId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    data = H.body()
    H.require_fields(data, ["department", "headcount", "call_start_at", "call_end_at",
                            "hourly_rate_cents"])
    c = base_fields()
    c.update({
        "engagement_id": e["id"],
        "department": H.req_enum(data, "department", LABOR_DEPARTMENTS),
        "headcount": H.req_int(data, "headcount"),
        "call_start_at": H.req_dt(data, "call_start_at"),
        "call_end_at": H.req_dt(data, "call_end_at"),
        "hourly_rate_cents": H.req_int(data, "hourly_rate_cents"),
        "status": "DRAFT",
        "effective_hours": None,
        "union_minimum_hours": None,
        "overtime_hours": None,
        "estimated_cost_cents": None,
        "final_cost_cents": None,
    })
    db.labor_calls[c["id"]] = c
    return success(c, 201)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_calls(tourId, engagementId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    items = [c for c in db.labor_calls.values() if c["engagement_id"] == engagementId]
    status = request.args.get("status")
    dept = request.args.get("department")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if dept is not None:
        items = [c for c in items if c["department"] == dept]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls/<callId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_call(tourId, engagementId, callId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    return success(H.get_labor_call(engagementId, callId))


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls/<callId>/post", methods=["POST"])
@require_roles("LaborSteward")
def post_call(tourId, engagementId, callId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    ticks.tick_engagement(e)
    c = H.get_labor_call(engagementId, callId)
    if c["status"] != "DRAFT":
        raise err("ERR_LABOR_CALL_NOT_DRAFT", "Call must be DRAFT to post")
    if e["status"] not in ("CONFIRMED", "IN_LOAD"):
        raise err("ERR_ENGAGEMENT_NOT_LABOR_READY",
                  "Engagement must be CONFIRMED or IN_LOAD to post labor")
    venue = db.venues[e["venue_id"]]
    est = calc.compute_labor_estimate(c, venue)
    c.update(est)
    c["status"] = "POSTED"
    touch(c)
    return success(c)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls/<callId>/fill", methods=["POST"])
@require_roles("LaborSteward")
def fill_call(tourId, engagementId, callId):
    H.get_tour(tourId)
    H.get_engagement(tourId, engagementId)
    c = H.get_labor_call(engagementId, callId)
    if c["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Call must be POSTED to fill")
    c["status"] = "FILLED"
    touch(c)
    return success(c)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls/<callId>/settle", methods=["POST"])
@require_roles("LaborSteward")
def settle_call(tourId, engagementId, callId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    c = H.get_labor_call(engagementId, callId)
    data = H.body()
    if c["status"] != "FILLED":
        raise err("ERR_INVALID_STATE", "Call must be FILLED to settle")
    punch_records = data.get("punch_records")
    if punch_records is None:
        raise err("ERR_INVALID_REQUEST", "punch_records required")
    if not isinstance(punch_records, list):
        raise err("ERR_INVALID_REQUEST", "punch_records must be an array")
    norm = []
    for rec in punch_records:
        if not isinstance(rec, dict):
            raise err("ERR_INVALID_REQUEST", "punch record must be an object")
        try:
            pin = H.req_dt(rec, "punch_in_at")
            pout = H.req_dt(rec, "punch_out_at")
        except Exception:
            raise err("ERR_INVALID_REQUEST", "invalid punch record timestamps")
        norm.append({"punch_in_at": pin, "punch_out_at": pout,
                     "created_at": rec.get("created_at") or ""})
    venue = db.venues[e["venue_id"]]
    c["final_cost_cents"] = calc.compute_labor_final(c, venue, norm)
    c["status"] = "SETTLED"
    touch(c)
    # apply delta to settlement if it already exists
    sid = db.settlements_by_eng.get(e["id"])
    if sid:
        s = db.settlements[sid]
        s["labor_total_cents"] = calc.compute_labor_total(e["id"])
        s["promoter_net_cents"] = calc.compute_promoter_net(
            s["gross_ticket_cents"], s["venue_share_cents"],
            s["royalty_withheld_cents"], s["labor_total_cents"])
        touch(s)
    return success(c)


@bp.route("/tours/<tourId>/engagements/<engagementId>/labor-calls/<callId>/cancel", methods=["POST"])
@require_roles("LaborSteward")
def cancel_call(tourId, engagementId, callId):
    H.get_tour(tourId)
    e = H.get_engagement(tourId, engagementId)
    c = H.get_labor_call(engagementId, callId)
    if c["status"] in ("DRAFT", "POSTED"):
        c["status"] = "CANCELLED"
        touch(c)
        return success(c)
    if c["status"] == "FILLED":
        notice_deadline = c["call_start_at"] - timedelta(hours=UNION_CANCEL_NOTICE_HOURS)
        if now() >= notice_deadline:
            raise err("ERR_LATE_LABOR_CANCEL",
                      "Cannot cancel FILLED call inside the notice window")
        fee = calc.round_half_up_cents(
            Decimal(c.get("estimated_cost_cents") or 0) * LATE_CANCEL_FEE_PCT)
        c["cancellation_fee_cents"] = fee
        c["status"] = "CANCELLED"
        touch(c)
        sid = db.settlements_by_eng.get(e["id"])
        if sid:
            s = db.settlements[sid]
            s["labor_total_cents"] = calc.compute_labor_total(e["id"]) + sum(
                x.get("cancellation_fee_cents") or 0
                for x in db.labor_calls.values()
                if x["engagement_id"] == e["id"] and x["status"] == "CANCELLED")
            s["promoter_net_cents"] = calc.compute_promoter_net(
                s["gross_ticket_cents"], s["venue_share_cents"],
                s["royalty_withheld_cents"], s["labor_total_cents"])
            touch(s)
        return success(c)
    raise err("ERR_INVALID_STATE", "Call in %s cannot be cancelled" % c["status"])
