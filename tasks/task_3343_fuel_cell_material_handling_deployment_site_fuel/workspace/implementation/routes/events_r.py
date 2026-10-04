"""Conversion event endpoints (PRD section 3.4)."""

from flask import Blueprint, g, request

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_FORBIDDEN, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE,
    ERR_TECHNICIAN_DOUBLE_BOOKED, ERR_TECHNICIAN_NOT_CERTIFIED,
)

bp = Blueprint("events", __name__)

READ_ROLES = ("SiteManager", "ConversionTechnician")


def _get_pair(pid, eid):
    plan = helpers.get_or_404(db.plans, pid, "conversion plan")
    e = helpers.get_or_404(db.events, eid, "conversion event")
    helpers.ensure_child(e, "conversion_plan_id", pid, "conversion event")
    return plan, e


def _check_ownership(e):
    if g.user_id != e["technician_id"]:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "only the assigned technician may act on this event")


def _site_of(plan):
    return helpers.get_site(plan["site_id"])


def _maybe_complete_plan(plan):
    if plan["status"] != "IN_PROGRESS":
        return
    evs = [x for x in db.events.values()
           if x["conversion_plan_id"] == plan["id"]]
    if (evs
            and all(x["status"] in ("COMPLETED", "CANCELLED") for x in evs)
            and any(x["status"] == "COMPLETED" for x in evs)):
        plan["status"] = "COMPLETED"
        helpers.touch(plan)


@bp.post("/api/conversion-plans/<pid>/conversion-events")
@require_roles("SiteManager")
def create_event(pid):
    plan = helpers.get_or_404(db.plans, pid, "conversion plan")
    site = _site_of(plan)
    helpers.ensure_site_open(site)
    data = v.body()
    forklift = v.str_value(v.req(data, "forklift_id"), "forklift_id", 1, 60)
    ss = v.datetime_value(v.req(data, "scheduled_start"), "scheduled_start")
    se = v.datetime_value(v.req(data, "scheduled_end"), "scheduled_end")
    tid = v.str_value(v.req(data, "technician_id"), "technician_id")
    sdt, edt = v.parse_datetime(ss), v.parse_datetime(se)
    if edt <= sdt:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "scheduled_end must be after scheduled_start")
    # Strict overlap against the same technician's SCHEDULED/IN_PROGRESS
    # events; merely touching windows are allowed.
    for e in db.events.values():
        if (e["technician_id"] == tid
                and e["status"] in ("SCHEDULED", "IN_PROGRESS")):
            os_ = v.parse_datetime(e["scheduled_start"])
            oe = v.parse_datetime(e["scheduled_end"])
            if sdt < oe and edt > os_:
                raise ApiError(ERR_TECHNICIAN_DOUBLE_BOOKED, 409,
                               "technician already has an overlapping "
                               "conversion event in that window")
    if tid not in db.technicians:
        raise ApiError(ERR_TECHNICIAN_NOT_CERTIFIED, 422,
                       "technician_id does not reference an existing technician")
    ev = helpers.create_rec(db.events, {
        "conversion_plan_id": pid,
        "forklift_id": forklift,
        "scheduled_start": ss,
        "scheduled_end": se,
        "technician_id": tid,
        "status": "SCHEDULED",
        "completed_at": None,
    })
    return envelope.ok(ev, 201)


@bp.get("/api/conversion-plans/<pid>/conversion-events")
@require_roles(*READ_ROLES)
def list_plan_events(pid):
    helpers.get_or_404(db.plans, pid, "conversion plan")
    items = [e for e in db.events.values() if e["conversion_plan_id"] == pid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/conversion-events/<eid>")
@require_roles(*READ_ROLES)
def get_event(eid):
    return envelope.ok(helpers.get_or_404(db.events, eid,
                                          "conversion event"), 200)


@bp.get("/api/conversion-events")
@require_roles(*READ_ROLES)
def list_events():
    items = list(db.events.values())
    plan_id = request.args.get("conversion_plan_id")
    if plan_id is not None:
        items = [e for e in items if e["conversion_plan_id"] == plan_id]
    tech_id = request.args.get("technician_id")
    if tech_id is not None:
        items = [e for e in items if e["technician_id"] == tech_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.post("/api/conversion-plans/<pid>/conversion-events/<eid>/start")
@require_roles("ConversionTechnician")
def start_event(pid, eid):
    plan, e = _get_pair(pid, eid)
    _check_ownership(e)
    if e["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "event must be SCHEDULED to start")
    site = _site_of(plan)
    helpers.ensure_site_open(site)
    if plan["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "parent plan must be SCHEDULED or IN_PROGRESS")
    tech = db.technicians.get(e["technician_id"])
    if (tech is None or not tech["active"]
            or v.parse_date(tech["certified_until"]) <= db.current_date()):
        raise ApiError(ERR_TECHNICIAN_NOT_CERTIFIED, 422,
                       "technician is inactive or certification has lapsed")
    e["status"] = "IN_PROGRESS"
    helpers.touch(e)
    if plan["status"] == "SCHEDULED":
        plan["status"] = "IN_PROGRESS"
        helpers.touch(plan)
    return envelope.ok(e, 200)


@bp.post("/api/conversion-plans/<pid>/conversion-events/<eid>/complete")
@require_roles("ConversionTechnician")
def complete_event(pid, eid):
    plan, e = _get_pair(pid, eid)
    _check_ownership(e)
    if e["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "event must be IN_PROGRESS to complete")
    site = _site_of(plan)
    helpers.ensure_site_open(site)
    e["status"] = "COMPLETED"
    e["completed_at"] = db.clock_stamp()
    helpers.touch(e)
    _maybe_complete_plan(plan)
    return envelope.ok(e, 200)


@bp.post("/api/conversion-plans/<pid>/conversion-events/<eid>/cancel")
@require_roles("ConversionTechnician")
def cancel_event(pid, eid):
    plan, e = _get_pair(pid, eid)
    _check_ownership(e)
    if e["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "event must be IN_PROGRESS to cancel")
    site = _site_of(plan)
    helpers.ensure_site_open(site)
    e["status"] = "CANCELLED"
    helpers.touch(e)
    _maybe_complete_plan(plan)
    return envelope.ok(e, 200)


@bp.post("/api/conversion-plans/<pid>/conversion-events/<eid>/unstart")
@require_roles("ConversionTechnician")
def unstart_event(pid, eid):
    plan, e = _get_pair(pid, eid)
    _check_ownership(e)
    if e["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "event must be IN_PROGRESS to unstart")
    site = _site_of(plan)
    helpers.ensure_site_open(site)
    e["status"] = "SCHEDULED"
    helpers.touch(e)
    return envelope.ok(e, 200)
