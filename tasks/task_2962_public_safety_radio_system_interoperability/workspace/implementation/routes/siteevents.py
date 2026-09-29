"""Site events: maintenance windows, outages, escalation and incident surge."""
from datetime import timedelta

from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import RF_ENGINEER, SYSTEM_ADMIN

bp = Blueprint("siteevents", __name__, url_prefix=common.PREFIX)

TERMINAL = ("CLOSED", "CANCELLED")
OPEN_EVENT_STATUSES = ("OPEN", "IN_PROGRESS")


def _planned_events(exclude_id=None):
    out = []
    for event in db.store.site_events.values():
        if event["event_class"] != "PLANNED_MAINTENANCE":
            continue
        if event["status"] not in OPEN_EVENT_STATUSES:
            continue
        if exclude_id is not None and event["id"] == exclude_id:
            continue
        out.append(event)
    return out


@bp.post("/site-events")
def create_site_event():
    validate.authenticate([SYSTEM_ADMIN, RF_ENGINEER])
    body = validate.get_body()
    site = validate.req_fk(body, "site_id", "sites")
    event_class = validate.req_enum(body, "event_class", enums.EVENT_CLASSES)
    cause = validate.req_enum(body, "cause", enums.EVENT_CAUSES)
    start = validate.opt_dt(body, "window_start")
    end = validate.opt_dt(body, "window_end")
    if event_class == "PLANNED_MAINTENANCE":
        if start is None or end is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "window_start and window_end are required for PLANNED_MAINTENANCE.",
            )
    elif start is not None or end is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "window_start and window_end must be omitted for this event_class.",
        )
    validate.window_order(start, end)
    if event_class == "PLANNED_MAINTENANCE":
        buffer_delta = timedelta(minutes=compute.MAINTENANCE_BUFFER_MINUTES)
        for other in _planned_events():
            if other["site_id"] != site["id"]:
                continue
            if start <= other["window_end"] + buffer_delta and \
                    other["window_start"] <= end + buffer_delta:
                raise ApiError("ERR_MAINTENANCE_BUFFER_VIOLATION")
        busy_sites = set()
        for other in _planned_events():
            if other["site_id"] == site["id"]:
                continue
            if start < other["window_end"] and other["window_start"] < end:
                busy_sites.add(other["site_id"])
        if len(busy_sites) >= compute.MAINTENANCE_CONCURRENCY_CAP:
            raise ApiError("ERR_MAINTENANCE_CONCURRENCY_CAP")
    row = db.base_row({
        "site_id": site["id"],
        "event_class": event_class,
        "cause": cause,
        "window_start": start,
        "window_end": end,
        "detected_at": db.now(),
        "status": "OPEN",
        "escalation_tier": 0,
        "backup_minutes_remaining": None,
        "restored_at": None,
        "preempted_talkpath_count": 0,
    })
    db.store.site_events[row["id"]] = row
    return response.ok(serialize.site_event(row), 201)


@bp.get("/site-events")
def list_site_events():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("site_id", validate.filter_str("site_id")),
        ("event_class", validate.filter_enum("event_class", enums.EVENT_CLASSES)),
        ("status", validate.filter_enum("status", enums.EVENT_STATUSES)),
    )
    return common.list_endpoint("site_events", serialize.site_event, filters)


@bp.get("/site-events/<event_id>")
def read_site_event(event_id):
    validate.authenticate(common.ANY_ROLE)
    event = validate.lookup("site_events", event_id)
    return response.ok(serialize.site_event(event))


def _tier_three_cascade(event, site, remaining):
    site["capacity_mode"] = "EMERGENCY_ONLY"
    site["status"] = "OFF_AIR" if remaining == 0 else "DEGRADED"
    db.touch(site)
    victims = compute.preemption_candidates(site["id"])
    for victim in victims:
        compute.preempt_request(victim)
    event["preempted_talkpath_count"] = len(victims)
    compute.recompute_site_counters(site)
    tg_ids = [
        t["id"] for t in db.store.talkgroups.values()
        if t["home_site_id"] == site["id"]
    ]
    if tg_ids:
        doomed = compute.open_patches_naming(tg_ids)
        if doomed:
            compute.release_patches(doomed, "SITE_ESCALATION")


@bp.post("/site-events/<event_id>/advance")
def advance_site_event(event_id):
    actor = validate.authenticate([SYSTEM_ADMIN, RF_ENGINEER])
    event = validate.lookup("site_events", event_id)
    body = validate.get_body()
    action = validate.req_enum(body, "action", enums.EVENT_ACTIONS)
    if action == "DECLARE_SURGE" and actor.role != SYSTEM_ADMIN:
        raise ApiError("ERR_UNAUTHORIZED", "DECLARE_SURGE is reserved to a SystemAdmin.")
    if event["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    site = db.store.sites.get(event["site_id"])
    event_class = event["event_class"]

    if action == "START":
        if event_class != "PLANNED_MAINTENANCE" or event["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if db.now() < event["window_start"]:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The maintenance window has not opened yet.",
            )
        event["status"] = "IN_PROGRESS"
        db.touch(event)
        compute.apply_fields(site, status="MAINTENANCE")
    elif action == "BACKUP_ENGAGED":
        if event_class != "UNPLANNED_OUTAGE" or event["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["status"] = "ON_BACKUP_POWER"
        event["backup_minutes_remaining"] = compute.backup_minutes_remaining(
            site, event["detected_at"]
        )
        db.touch(event)
        compute.apply_fields(site, status="DEGRADED")
    elif action == "DECLARE_SURGE":
        if event_class != "MAJOR_INCIDENT" or event["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if site is not None and site["status"] == "OFF_AIR":
            raise ApiError("ERR_SITE_OFF_AIR")
        event["status"] = "SURGE_ACTIVE"
        db.touch(event)
        compute.apply_fields(site, capacity_mode="PRIORITY_ONLY")
    elif action == "ESCALATE":
        if event["status"] not in ("ON_BACKUP_POWER", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        remaining = compute.backup_minutes_remaining(site, event["detected_at"])
        tier = compute.escalation_tier_for(remaining)
        if tier <= event["escalation_tier"]:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Escalation must raise the tier.",
            )
        event["backup_minutes_remaining"] = remaining
        event["status"] = "ESCALATED"
        event["escalation_tier"] = tier
        db.touch(event)
        if tier == 3:
            _tier_three_cascade(event, site, remaining)
    elif action == "RESTORE":
        if event["status"] not in ("ON_BACKUP_POWER", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["status"] = "RESTORED"
        event["restored_at"] = db.now()
        event["backup_minutes_remaining"] = None
        db.touch(event)
        compute.apply_fields(site, status="IN_SERVICE", capacity_mode="NORMAL")
    elif action == "CLOSE":
        if event["status"] not in ("IN_PROGRESS", "SURGE_ACTIVE", "RESTORED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["status"] = "CLOSED"
        db.touch(event)
        compute.apply_fields(site, status="IN_SERVICE", capacity_mode="NORMAL")
    else:  # CANCEL
        if event["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        event["status"] = "CANCELLED"
        db.touch(event)
    return response.ok(serialize.site_event(event))
