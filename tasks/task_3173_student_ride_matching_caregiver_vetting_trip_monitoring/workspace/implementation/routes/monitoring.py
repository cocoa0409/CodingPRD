"""Monitoring clock and support-centre / system-event operations.

  POST /_clock/set_current_utc
  POST /_support-center/monitor-sweep
  POST /_events/emit
"""

import calculations as calc
import db
import models
import services
import validators as v
from clock import clock_date, now_utc, parse_date, set_clock
from errors import ERR_INVALID_REQUEST, ERR_INVALID_STATE, ApiError, not_found
from flask import Blueprint, request
from middleware import requires
from response import empty_response, object_response

bp = Blueprint("monitoring", __name__)

CLOCK_INPUT = ("to_iso8601",)
SWEEP_INPUT = ("trip_id",)
EVENT_INPUT = ("event_type", "effective_date", "district_id")

TRIP_DELAY = "TRIP_DELAY"
GEOFENCE_BREACH = "GEOFENCE_BREACH"


@bp.post("/_clock/set_current_utc")
@requires("PlatformAdmin")
def set_current_utc():
    data = v.body()
    v.reject_unknown(data, CLOCK_INPUT)
    to_iso = v.as_string(data, "to_iso8601")
    try:
        set_clock(to_iso)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant.")
    return empty_response()


@bp.post("/_support-center/monitor-sweep")
@requires("SupportCenterAgent", "PlatformAdmin")
def monitor_sweep():
    data = v.body()
    v.reject_unknown(data, SWEEP_INPUT)
    trip_id = v.as_string(data, "trip_id")
    trip = db.get("trips", trip_id)
    if trip is None:
        raise not_found("The addressed trip does not exist.")
    if trip["trip_state"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "A monitoring sweep only applies to a trip that has not finished.",
        )

    now = now_utc()
    window_start = services.trip_window_instant(trip["window_start_at"])
    window_end = services.trip_window_instant(trip["window_end_at"])
    raised = 0

    if trip["trip_state"] == "SCHEDULED" and now > window_end:
        # The trip was never claimed and its window has closed without pickup.
        services.create_trip_alert(trip, TRIP_DELAY, source_incident_id=None)
        raised += 1
    elif trip["trip_state"] in ("DRIVER_EN_ROUTE", "AWAITING_STUDENT") and now > window_end:
        # The pickup handoff never happened.
        services.create_trip_alert(trip, TRIP_DELAY, source_incident_id=None)
        raised += 1
    elif trip["trip_state"] == "IN_TRANSIT" and now > window_end:
        # The dropoff handoff never happened.
        services.create_trip_alert(trip, TRIP_DELAY, source_incident_id=None)
        raised += 1
    elif trip["trip_state"] == "STUDENT_ONBOARD" and now > window_start:
        # A monitored trip that has not departed on schedule.
        services.create_trip_alert(trip, TRIP_DELAY, source_incident_id=None)
        raised += 1

    db.bump_version(trip)
    return object_response(models.trip_out(trip))


@bp.post("/_events/emit")
@requires("DistrictAdmin", "PlatformAdmin")
def emit_event():
    data = v.body()
    v.reject_unknown(data, EVENT_INPUT)
    event_type = v.as_string(data, "event_type")
    effective_date = v.as_iso_date_string(data, "effective_date")
    district_id = v.as_string(data, "district_id")
    district = db.get("districts", district_id)
    if district is None:
        raise not_found("The addressed district does not exist.")

    if event_type != "NO_SCHOOL_DAY":
        raise ApiError(ERR_INVALID_REQUEST, "event_type must be NO_SCHOOL_DAY.")

    dates = list(district.get("no_school_dates") or [])
    if effective_date not in dates:
        dates.append(effective_date)
        district["no_school_dates"] = dates
    db.touch(district)

    # The closure reaches every scheduled, active recurring series immediately.
    for rr in db.all_of("ride_requests"):
        if rr["district_id"] != district_id:
            continue
        if rr["status"] != "SCHEDULED" or not rr.get("recurring_series_active"):
            continue
        for trip in db.all_of("trips"):
            if trip["ride_request_id"] != rr["id"]:
                continue
            if trip["scheduled_date"] != effective_date:
                continue
            if trip["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
                continue
            trip["trip_state"] = "CANCELLED"
            trip["candidate_driver_id"] = None
            db.bump_version(trip)
    calc.recompute_district(district)
    db.bump_version(district)
    return object_response(models.district_out(district))