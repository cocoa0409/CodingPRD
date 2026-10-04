"""Shared helpers: body validation, entity lookup, lazy clock ticks, cascades."""
from datetime import timedelta

from flask import request

import clock
from clock import now
from db import db, touch
from errors import err

OPEN_ENGAGEMENT_STATUSES = ["HOLD", "CONFIRMED", "IN_LOAD", "SHOW_READY", "IN_PERFORMANCE"]
PRORATE_ENGAGEMENT_STATUSES = ["CONFIRMED", "IN_LOAD", "SHOW_READY", "IN_PERFORMANCE", "SETTLED"]
PLAN_NONTERMINAL = ["DRAFT", "SUBMITTED", "REJECTED"]


# ---------- request body ----------

def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "JSON object body required")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def req_str(data, f):
    v = data.get(f)
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % f)
    return v


def opt_str(data, f, default=None):
    v = data.get(f, default)
    if v is not None and not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % f)
    return v


def req_int(data, f):
    v = data.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % f)
    return v


def opt_int(data, f, default):
    v = data.get(f, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % f)
    return v


def opt_bool(data, f, default):
    v = data.get(f, default)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % f)
    return v


def opt_num(data, f, default):
    v = data.get(f, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % f)
    return v


def req_enum(data, f, allowed):
    v = data.get(f)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (f, allowed))
    return v


def req_dt(data, f):
    v = data.get(f)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO8601 string" % f)
    try:
        return clock._parse(v)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO8601 timestamp" % f)


# ---------- entity lookups ----------

def get_tour(tid):
    t = db.tours.get(tid)
    if t is None:
        raise err("ERR_TOUR_NOT_FOUND", "Tour not found: %s" % tid)
    return t


def get_venue(vid):
    v = db.venues.get(vid)
    if v is None:
        raise err("ERR_VENUE_NOT_FOUND", "Venue not found: %s" % vid)
    return v


def get_point(vid, pid):
    p = db.rigging_points.get(pid)
    if p is None or p["venue_id"] != vid:
        raise err("ERR_POINT_NOT_FOUND", "RiggingPoint not found: %s" % pid)
    return p


def get_avail(vid, aid):
    a = db.date_avails.get(aid)
    if a is None or a["venue_id"] != vid:
        raise err("ERR_AVAIL_NOT_FOUND", "DateAvail not found: %s" % aid)
    return a


def get_engagement(tid, eid):
    e = db.engagements.get(eid)
    if e is None or e["tour_id"] != tid:
        raise err("ERR_ENGAGEMENT_NOT_FOUND", "Engagement not found: %s" % eid)
    return e


def get_plan(tid, eid, pid):
    p = db.rigging_plans.get(pid)
    if p is None or p["engagement_id"] != eid:
        raise err("ERR_PLAN_NOT_FOUND", "RiggingPlan not found: %s" % pid)
    return p


def get_labor_call(eid, cid):
    c = db.labor_calls.get(cid)
    if c is None or c["engagement_id"] != eid:
        raise err("ERR_LABOR_CALL_NOT_FOUND", "LaborCall not found: %s" % cid)
    return c


def get_truck_move(eid, mid):
    m = db.truck_moves.get(mid)
    if m is None or m["engagement_id"] != eid:
        raise err("ERR_TRUCK_MOVE_NOT_FOUND", "TruckMove not found: %s" % mid)
    return m


def get_ticket_scale(eid, sid):
    s = db.ticket_scales.get(sid)
    if s is None or s["engagement_id"] != eid:
        raise err("ERR_TICKET_SCALE_NOT_FOUND", "TicketScale not found: %s" % sid)
    return s


def get_settlement(eid):
    sid = db.settlements_by_eng.get(eid)
    s = db.settlements.get(sid) if sid else None
    if s is None:
        raise err("ERR_SETTLEMENT_NOT_FOUND", "Settlement not found for engagement: %s" % eid)
    return s


def get_license(tid, lid):
    l = db.license_agreements.get(lid)
    if l is None or l["tour_id"] != tid:
        raise err("ERR_LICENSE_NOT_FOUND", "LicenseAgreement not found: %s" % lid)
    return l


def get_inspection(eid, iid):
    i = db.safety_inspections.get(iid)
    if i is None or i["engagement_id"] != eid:
        raise err("ERR_INSPECTION_NOT_FOUND", "SafetyInspection not found: %s" % iid)
    return i
