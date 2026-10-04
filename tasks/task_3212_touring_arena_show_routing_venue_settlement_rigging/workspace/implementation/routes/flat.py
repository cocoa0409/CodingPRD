"""Flat read aliases for FK reverse-reachability plus the logical clock endpoint."""
from flask import Blueprint, request

import clock
from constants import ALL_ROLES
from db import db
from errors import err
from middleware import require_roles
from response import success, paginate
import helpers as H
import ticks
from routes.engagements import engagement_view

bp = Blueprint("flat", __name__)

SETTLEMENT_READ_ROLES = ("TourManager", "VenueBooker", "BoxOfficeManager", "PlatformAdmin")


# ---------- clock ----------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    data = H.body()
    H.require_fields(data, ["to_iso8601"])
    iso = H.req_str(data, "to_iso8601")
    try:
        current = clock.set_current(iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO8601 timestamp")
    ticks.tick_all()
    return success({"current_utc": current})


# ---------- engagements ----------

@bp.route("/engagements/<eid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_engagement(eid):
    e = db.engagements.get(eid)
    if e is None:
        raise err("ERR_ENGAGEMENT_NOT_FOUND", "Engagement not found: %s" % eid)
    return success(engagement_view(e))


@bp.route("/engagements", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_engagements():
    items = list(db.engagements.values())
    for e in items:
        ticks.tick_engagement(e)
    for key in ("tour_id", "venue_id", "date_avail_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [e for e in items if e.get(key) == v]
    items = [engagement_view(e) for e in items]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- date avails ----------

@bp.route("/date-avails/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_avail(aid):
    a = db.date_avails.get(aid)
    if a is None:
        raise err("ERR_AVAIL_NOT_FOUND", "DateAvail not found: %s" % aid)
    return success(a)


@bp.route("/date-avails", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_avails():
    items = list(db.date_avails.values())
    for key in ("venue_id", "held_for_engagement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- rigging points ----------

@bp.route("/rigging-points/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_point(pid):
    p = db.rigging_points.get(pid)
    if p is None:
        raise err("ERR_POINT_NOT_FOUND", "RiggingPoint not found: %s" % pid)
    return success(p)


@bp.route("/rigging-points", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_points():
    items = list(db.rigging_points.values())
    for key in ("venue_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [p for p in items if p.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- rigging plans ----------

@bp.route("/rigging-plans/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_plan(pid):
    p = db.rigging_plans.get(pid)
    if p is None:
        raise err("ERR_PLAN_NOT_FOUND", "RiggingPlan not found: %s" % pid)
    return success(p)


@bp.route("/rigging-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_plans():
    items = list(db.rigging_plans.values())
    for key in ("engagement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [p for p in items if p.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- rigging allocations ----------

@bp.route("/rigging-allocations/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_allocation(aid):
    a = db.rigging_allocations.get(aid)
    if a is None:
        raise err("ERR_INVALID_REQUEST", "RiggingAllocation not found: %s" % aid)
    return success(a)


@bp.route("/rigging-allocations", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_allocations():
    items = list(db.rigging_allocations.values())
    for key in ("rigging_plan_id", "rigging_point_id"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if a.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- labor calls ----------

@bp.route("/labor-calls/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_call(cid):
    c = db.labor_calls.get(cid)
    if c is None:
        raise err("ERR_LABOR_CALL_NOT_FOUND", "LaborCall not found: %s" % cid)
    return success(c)


@bp.route("/labor-calls", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_calls():
    items = list(db.labor_calls.values())
    for key in ("engagement_id", "status", "department"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- truck moves ----------

@bp.route("/truck-moves/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_move(mid):
    m = db.truck_moves.get(mid)
    if m is None:
        raise err("ERR_TRUCK_MOVE_NOT_FOUND", "TruckMove not found: %s" % mid)
    return success(m)


@bp.route("/truck-moves", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_moves():
    items = list(db.truck_moves.values())
    for key in ("engagement_id", "status", "cargo_kind"):
        v = request.args.get(key)
        if v is not None:
            items = [m for m in items if m.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- ticket scales ----------

@bp.route("/ticket-scales/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_scale(sid):
    s = db.ticket_scales.get(sid)
    if s is None:
        raise err("ERR_TICKET_SCALE_NOT_FOUND", "TicketScale not found: %s" % sid)
    return success(s)


@bp.route("/ticket-scales", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_scales():
    items = list(db.ticket_scales.values())
    v = request.args.get("engagement_id")
    if v is not None:
        items = [s for s in items if s.get("engagement_id") == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- settlements ----------

@bp.route("/settlements/<sid>", methods=["GET"])
@require_roles(*SETTLEMENT_READ_ROLES)
def flat_get_settlement(sid):
    s = db.settlements.get(sid)
    if s is None:
        raise err("ERR_SETTLEMENT_NOT_FOUND", "Settlement not found: %s" % sid)
    return success(s)


@bp.route("/settlements", methods=["GET"])
@require_roles(*SETTLEMENT_READ_ROLES)
def flat_list_settlements():
    items = list(db.settlements.values())
    for key in ("engagement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [s for s in items if s.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- license agreements ----------

@bp.route("/license-agreements/<lid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_license(lid):
    l = db.license_agreements.get(lid)
    if l is None:
        raise err("ERR_LICENSE_NOT_FOUND", "LicenseAgreement not found: %s" % lid)
    ticks.tick_license(l)
    return success(l)


@bp.route("/license-agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_licenses():
    items = list(db.license_agreements.values())
    for l in items:
        ticks.tick_license(l)
    for key in ("tour_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if l.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


# ---------- safety inspections ----------

@bp.route("/safety-inspections/<iid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_get_inspection(iid):
    i = db.safety_inspections.get(iid)
    if i is None:
        raise err("ERR_INSPECTION_NOT_FOUND", "SafetyInspection not found: %s" % iid)
    return success(i)


@bp.route("/safety-inspections", methods=["GET"])
@require_roles(*ALL_ROLES)
def flat_list_inspections():
    items = list(db.safety_inspections.values())
    for key in ("engagement_id", "status", "inspection_kind"):
        v = request.args.get(key)
        if v is not None:
            items = [i for i in items if i.get(key) == v]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)
