"""Downtime events: root cause, minute geometry and the reporting ledger."""

from flask import Blueprint

import calc
import derive
import fetch
import store
import validate
from auth import ALL_ROLES, require_roles
from envelope import list_response
from errors import (
    fail,
    invalid,
    ERR_COMPONENT_ATTRACTION_MISMATCH,
    ERR_DOWNTIME_ALREADY_OPEN,
    ERR_DOWNTIME_SPANS_SERVICE_DATES,
    ERR_DOWNTIME_STATE_INVALID,
)
from reply import computed, made, saved

bp = Blueprint("downtime", __name__)

CAUSE_CATEGORIES = ("MECHANICAL", "ELECTRICAL", "GUEST_ILLNESS", "WEATHER",
                    "INSPECTION_FAIL", "OPERATOR")


@bp.post("/park-ops/downtime-events")
@require_roles("MaintenanceTechnician")
def open_downtime():
    data = validate.body()
    attraction = fetch.fk("attractions", data.get("attraction_id"))
    validate.id_field(data, "attraction_id")
    started_at = validate.instant_field(data, "started_at")
    cause_category = validate.enum_field(data, "cause_category",
                                         CAUSE_CATEGORIES)
    for event in store.rows("downtime_events"):
        if (event["attraction_id"] == attraction["id"]
                and event["status"] in derive.LIVE_DOWNTIME):
            fail(ERR_DOWNTIME_ALREADY_OPEN,
                 "The attraction already holds a live downtime event.")
    row = store.create(
        "downtime_events",
        attraction_id=attraction["id"],
        failed_component_id=None,
        started_at=store.iso(started_at),
        ended_at=None,
        service_date=started_at.date().isoformat(),
        cause_category=cause_category,
        root_cause_code=None,
        status="OPEN",
        duration_minutes=None,
        peak_minutes=None,
        off_peak_minutes=None,
        _settled_hundredths=None,
        void_reason=None,
        auto_opened=False,
    )
    return made(derive.ser_downtime_event, row)


@bp.get("/park-ops/downtime-events/<event_id>")
@require_roles(*ALL_ROLES)
def read_downtime(event_id):
    return computed(derive.ser_downtime_event(fetch.downtime_event(event_id)))


@bp.get("/park-ops/downtime-events")
@require_roles(*ALL_ROLES)
def list_downtime():
    return list_response(
        store.rows("downtime_events"),
        derive.ser_downtime_event,
        filters=(("attraction_id", "str"), ("failed_component_id", "str"),
                 ("status", "str"), ("service_date", "str"),
                 ("cause_category", "str"), ("auto_opened", "bool")),
        order=("service_date", "started_at"),
    )


@bp.post("/park-ops/downtime-events/<event_id>/diagnose")
@require_roles("MaintenanceTechnician")
def diagnose_downtime(event_id):
    event = fetch.downtime_event(event_id)
    data = validate.body()
    component = fetch.fk("components", data.get("failed_component_id"))
    root_cause_code = validate.str_field(data, "root_cause_code",
                                         allow_empty=True)
    if event["status"] != "OPEN":
        fail(ERR_DOWNTIME_STATE_INVALID,
             "Only an OPEN downtime event may be diagnosed.")
    if component is not None:
        if component["attraction_id"] != event["attraction_id"]:
            fail(ERR_COMPONENT_ATTRACTION_MISMATCH,
                 "The component is installed on a different attraction.")
    event["status"] = "DIAGNOSED"
    event["root_cause_code"] = root_cause_code
    event["failed_component_id"] = component["id"] if component else None
    if component is not None:
        component["condition_flag"] = "FAILED"
    return saved(derive.ser_downtime_event, event)


@bp.post("/park-ops/downtime-events/<event_id>/resolve")
@require_roles("MaintenanceTechnician")
def resolve_downtime(event_id):
    event = fetch.downtime_event(event_id)
    data = validate.body()
    ended_at = validate.instant_field(data, "ended_at")
    started_at = store.instant_of(event["started_at"])
    if ended_at <= started_at:
        invalid("ended_at must be strictly later than started_at.")
    if event["status"] != "DIAGNOSED":
        fail(ERR_DOWNTIME_STATE_INVALID,
             "Only a DIAGNOSED downtime event may be resolved.")
    service_date = store.date_of(event["service_date"])
    if ended_at.date() != service_date:
        fail(ERR_DOWNTIME_SPANS_SERVICE_DATES,
             "ended_at must fall on the event's pinned service_date.")
    attraction = store.db.attractions.get(event["attraction_id"])
    duration, peak, off_peak = calc.geometry(started_at, ended_at,
                                             service_date)
    event["status"] = "RESOLVED"
    event["ended_at"] = store.iso(ended_at)
    event["duration_minutes"] = duration
    event["peak_minutes"] = peak
    event["off_peak_minutes"] = off_peak
    event["_settled_hundredths"] = calc.settled_hundredths(attraction, peak,
                                                           off_peak)
    return saved(derive.ser_downtime_event, event)


@bp.post("/park-ops/downtime-events/<event_id>/close")
@require_roles("MaintenanceManager")
def close_downtime(event_id):
    event = fetch.downtime_event(event_id)
    validate.body()
    if event["status"] != "RESOLVED":
        fail(ERR_DOWNTIME_STATE_INVALID,
             "Only a RESOLVED downtime event may be closed.")
    event["status"] = "CLOSED"
    return saved(derive.ser_downtime_event, event)


@bp.post("/park-ops/downtime-events/<event_id>/void")
@require_roles("MaintenanceManager")
def void_downtime(event_id):
    event = fetch.downtime_event(event_id)
    data = validate.body()
    reason = validate.str_field(data, "void_reason", allow_empty=True)
    if event["status"] != "CLOSED":
        fail(ERR_DOWNTIME_STATE_INVALID,
             "Only a CLOSED downtime event may be voided.")
    event["status"] = "VOIDED"
    event["void_reason"] = reason
    return saved(derive.ser_downtime_event, event)
