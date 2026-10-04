"""RideRequest endpoints: intake, approval, the revision cycle and scheduling."""

import calculations as calc
import db
import models
import services
import validators as v
from clock import clock_date, now_utc, parse_date
from datetime import timedelta, timezone
from decimal import Decimal
from errors import (
    ERR_ALREADY_SCHEDULED,
    ERR_ALREADY_TERMINAL,
    ERR_DRIVER_INELIGIBLE,
    ERR_DRIVER_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LEAD_TIME_TOO_SHORT,
    ERR_NO_ELIGIBLE_DRIVER,
    ERR_NO_SCHOOL_DAYS_IN_RANGE,
    ERR_NOT_RECURRING,
    ERR_OUTSIDE_SCHOOL_TERM,
    ERR_RIDER_INACTIVE,
    ERR_RIDER_WINDOW_OVERLAP,
    ERR_SERIES_ENDED,
    ERR_TRIP_IN_PROGRESS,
    ERR_WINDOW_TOO_WIDE,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("ride_requests", __name__)

RIDE_REQUEST_INPUT = (
    "expected_district_version", "district_id", "rider_id", "trip_type",
    "required_specialty", "window_start_at", "window_end_at", "max_window_minutes",
    "min_lead_time_hours", "pickup_address", "dropoff_address", "planned_miles",
    "is_recurring", "days_of_week", "series_effective_from", "series_through_date",
    "series_no_school_dates",
)

TERMINAL_STATUSES = ("REJECTED", "CANCELLED")


def load_ride_request(rr_id):
    rr = db.get("ride_requests", rr_id)
    if rr is None:
        raise not_found("The addressed ride request does not exist.")
    return rr


def _state_gate(current, required, msg):
    if isinstance(required, str):
        required = (required,)
    if current in required:
        return
    if current in TERMINAL_STATUSES:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The ride request has already reached a terminal state.",
        )
    raise ApiError(ERR_INVALID_STATE, msg)


def _window_checks(rr):
    """Order then width; both report ERR_WINDOW_TOO_WIDE (PRD section 3.4)."""
    start = services.trip_window_instant(rr["window_start_at"])
    end = services.trip_window_instant(rr["window_end_at"])
    if not start < end:
        raise ApiError(
            ERR_WINDOW_TOO_WIDE,
            "window_start_at must fall strictly before window_end_at.",
        )
    span_minutes = (end - start).total_seconds() / 60.0
    if span_minutes > rr["max_window_minutes"]:
        raise ApiError(
            ERR_WINDOW_TOO_WIDE,
            "The pickup window is wider than max_window_minutes permits.",
        )


@bp.post("/student-rides/ride-requests")
@requires("DistrictAdmin", "PlatformAdmin")
def create_ride_request():
    data = v.body()
    v.reject_unknown(data, RIDE_REQUEST_INPUT)
    district_id = v.as_string(data, "district_id")
    district = db.get("districts", district_id)
    if district is None:
        raise not_found("The addressed district does not exist.")

    # OCC (SCAFFOLD section 1.2.1): checked before the rider is resolved, so a
    # stale caller never learns about the child resource.
    from routes.districts import check_stale
    check_stale(district, data)

    rider_id = v.as_string(data, "rider_id")
    rider = db.get("riders", rider_id)
    if rider is None:
        raise not_found("The addressed rider does not exist.")

    is_recurring = v.as_bool(data, "is_recurring", default=False)
    days_of_week = v.as_array(data, "days_of_week", default=[]) or []
    series_from = v.as_iso_date_string(data, "series_effective_from", required_field=False)
    series_through = v.as_iso_date_string(data, "series_through_date", required_field=False)
    series_excluded = v.as_array(data, "series_no_school_dates", default=[]) or []

    if is_recurring and series_from and series_through:
        if not series_from <= series_through:
            raise ApiError(ERR_INVALID_REQUEST, "series_effective_from must not follow series_through_date.")

    rr = db.new_record({
        "district_id": district_id,
        "rider_id": rider_id,
        "trip_type": v.enum_value("trip_type", v.required(data, "trip_type")),
        "required_specialty": v.enum_value("required_specialty", data.get("required_specialty", "NONE")),
        "window_start_at": services.fmt_or_none(v.as_iso_dt(data, "window_start_at")),
        "window_end_at": services.fmt_or_none(v.as_iso_dt(data, "window_end_at")),
        "max_window_minutes": v.as_int(data, "max_window_minutes", default=30),
        "min_lead_time_hours": v.as_int(data, "min_lead_time_hours", default=12),
        "pickup_address": v.as_string(data, "pickup_address"),
        "dropoff_address": v.as_string(data, "dropoff_address"),
        "planned_miles": v.as_number(data, "planned_miles", default=0),
        "is_recurring": is_recurring,
        "days_of_week": days_of_week,
        "series_effective_from": series_from,
        "series_through_date": series_through,
        "series_no_school_dates": [str(d) for d in series_excluded],
        "revision_count": 0,
        "status": "DRAFT",
        "recurring_series_active": False,
    })
    db.save("ride_requests", rr)
    # The create advances the district's version (SCAFFOLD endpoint table).
    db.bump_version(district)
    return object_response(models.ride_request_out(rr), 201)


@bp.get("/student-rides/ride-requests/<rr_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def get_ride_request(rr_id):
    return object_response(models.ride_request_out(load_ride_request(rr_id)))


@bp.get("/student-rides/ride-requests/<rr_id>/trips")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_ride_request_trips(rr_id):
    load_ride_request(rr_id)
    rows = [t for t in db.all_of("trips") if t["ride_request_id"] == rr_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("trips", page), limit, offset, total)


@bp.post("/student-rides/ride-requests/<rr_id>/submit")
@requires("DistrictAdmin", "PlatformAdmin")
def submit_ride_request(rr_id):
    rr = load_ride_request(rr_id)
    _state_gate(rr["status"], "DRAFT", "Only a DRAFT ride request may be submitted.")
    _window_checks(rr)
    rr["status"] = "SUBMITTED"
    db.bump_version(rr)
    rider = db.get("riders", rr["rider_id"])
    if rider:
        calc.recompute_rider(rider)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/request-revision")
@requires("DistrictAdmin", "PlatformAdmin")
def request_revision(rr_id):
    rr = load_ride_request(rr_id)
    data = v.body()
    v.reject_unknown(data, ("revision_note",))
    v.as_string(data, "revision_note", required_field=False)
    _state_gate(rr["status"], "SUBMITTED", "Only a SUBMITTED ride request may be returned for revision.")
    rr["status"] = "REVISION_REQUESTED"
    rr["revision_count"] = int(rr.get("revision_count") or 0) + 1
    db.bump_version(rr)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/resubmit")
@requires("DistrictAdmin", "PlatformAdmin")
def resubmit(rr_id):
    rr = load_ride_request(rr_id)
    _state_gate(rr["status"], "REVISION_REQUESTED", "Only a REVISION_REQUESTED ride request may be resubmitted.")
    rr["status"] = "SUBMITTED"
    db.bump_version(rr)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/approve")
@requires("DistrictAdmin", "PlatformAdmin")
def approve(rr_id):
    rr = load_ride_request(rr_id)
    _state_gate(rr["status"], "SUBMITTED", "Only a SUBMITTED ride request may be approved.")
    _window_checks(rr)

    rider = db.get("riders", rr["rider_id"])
    if rider is None or rider["status"] != "ACTIVE":
        raise ApiError(ERR_RIDER_INACTIVE, "The student is not in ACTIVE status.")

    if rr["is_recurring"]:
        if not rr.get("series_effective_from"):
            raise ApiError(ERR_INVALID_REQUEST, "A recurring request requires series_effective_from.")
        if parse_date(rr["series_effective_from"]) < calc.ACADEMIC_TERM_OPEN_DATE:
            raise ApiError(
                ERR_OUTSIDE_SCHOOL_TERM,
                "The series effective date precedes the academic term opening date.",
            )
        days = rr.get("days_of_week") or []
        if not days or any(not isinstance(d, int) or d < 1 or d > 7 for d in days):
            raise ApiError(
                ERR_INVALID_REQUEST,
                "A recurring request requires at least one ISO weekday integer in days_of_week.",
            )
    else:
        start = services.trip_window_instant(rr["window_start_at"])
        lead_hours = (start - now_utc()).total_seconds() / 3600.0
        if lead_hours < rr["min_lead_time_hours"]:
            raise ApiError(
                ERR_LEAD_TIME_TOO_SHORT,
                "The request was approved with less than min_lead_time_hours before its pickup window.",
            )

    rr["status"] = "APPROVED"
    db.bump_version(rr)
    calc.recompute_rider(rider)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/reject")
@requires("DistrictAdmin", "PlatformAdmin")
def reject(rr_id):
    rr = load_ride_request(rr_id)
    data = v.body()
    v.reject_unknown(data, ("reason",))
    v.as_string(data, "reason", required_field=False)
    _state_gate(rr["status"], ("SUBMITTED", "APPROVED"), "Only a SUBMITTED or APPROVED request may be rejected.")
    rr["status"] = "REJECTED"
    rr["recurring_series_active"] = False
    db.bump_version(rr)
    rider = db.get("riders", rr["rider_id"])
    if rider:
        calc.recompute_rider(rider)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/cancel")
@requires("DistrictAdmin", "PlatformAdmin")
def cancel(rr_id):
    rr = load_ride_request(rr_id)
    data = v.body()
    v.reject_unknown(data, ("reason",))
    _state_gate(rr["status"], ("DRAFT", "SERIES_SUSPENDED"), "Only a DRAFT or SERIES_SUSPENDED request may be cancelled.")
    rr["status"] = "CANCELLED"
    rr["recurring_series_active"] = False
    db.bump_version(rr)
    rider = db.get("riders", rr["rider_id"])
    if rider:
        calc.recompute_rider(rider)
    return object_response(models.ride_request_out(rr))


# --- Scheduling --------------------------------------------------------------

SCHEDULE_INPUT = ("scheduled_date",)


@bp.post("/student-rides/ride-requests/<rr_id>/schedule")
@requires("DistrictAdmin", "PlatformAdmin")
def schedule(rr_id):
    rr = load_ride_request(rr_id)
    data = v.body()
    v.reject_unknown(data, SCHEDULE_INPUT)
    _state_gate(rr["status"], "APPROVED", "Only an APPROVED ride request may be scheduled.")

    district = db.get("districts", rr["district_id"])

    if rr["is_recurring"]:
        iso_dates = calc.recurring_allocation_dates(rr)
        if not iso_dates:
            raise ApiError(
                ERR_NO_SCHOOL_DAYS_IN_RANGE,
                "The recurring series produces zero included dates over its window.",
            )
        windows = services.build_trip_windows(rr, iso_dates)

        # No included date may touch or overlap an existing non-terminal trip
        # window for the same rider (closed intervals).
        if services.rider_window_collision(rr["rider_id"], [(s, e) for (_, s, e) in windows]):
            raise ApiError(
                ERR_RIDER_WINDOW_OVERLAP,
                "A generated trip window touches or overlaps an existing trip window for this student.",
            )

        # Every included date must yield at least one eligible candidate, and no
        # date may collide with a driver's existing occupancy (half-open).
        for (iso, start, end) in windows:
            d = parse_date(iso)
            candidate = calc.dispatch_rank(rr, d)
            if candidate is None:
                raise ApiError(
                    ERR_NO_ELIGIBLE_DRIVER,
                    "No eligible driver exists for at least one required date.",
                )
            if services.driver_series_overlap(rr, [(start, end)], candidate):
                raise ApiError(
                    ERR_DRIVER_WINDOW_OVERLAP,
                    "A generated trip window overlaps an interval already occupied by the selected driver.",
                )

        created = []
        for (iso, start, end) in windows:
            d = parse_date(iso)
            candidate = calc.dispatch_rank(rr, d)
            trip = services.create_trip(rr, iso, start, end, district_version_bump=False)
            trip["candidate_driver_id"] = candidate["id"] if candidate else None
            created.append(trip)

        rr["status"] = "SCHEDULED"
        rr["recurring_series_active"] = True
        db.bump_version(rr)
        if district:
            calc.recompute_district(district)
            db.bump_version(district)
        rider = db.get("riders", rr["rider_id"])
        if rider:
            calc.recompute_rider(rider)
        return array_response(models.serialise_all("trips", created), status=201)

    # One-off scheduling.
    scheduled_date = v.as_iso_date_string(data, "scheduled_date")
    for trip in db.all_of("trips"):
        if trip["ride_request_id"] == rr["id"] and trip["scheduled_date"] == scheduled_date:
            raise ApiError(
                ERR_ALREADY_SCHEDULED,
                "A trip already exists for this ride request and scheduled date.",
            )

    d = parse_date(scheduled_date)
    windows = services.build_trip_windows(rr, [scheduled_date])
    _, start, end = windows[0]

    # An explicit scheduled_date supplies the date; the request's time-of-day
    # component binds to it, exactly as for a generated trip.
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)

    if services.rider_window_collision(rr["rider_id"], [(start, end)]):
        raise ApiError(
            ERR_RIDER_WINDOW_OVERLAP,
            "The trip window touches or overlaps an existing trip window for this student.",
        )
    candidate = calc.dispatch_rank(rr, d)
    if candidate is None:
        raise ApiError(ERR_NO_ELIGIBLE_DRIVER, "No eligible driver exists for the requested date.")
    if services.driver_series_overlap(rr, [(start, end)], candidate):
        raise ApiError(
            ERR_DRIVER_WINDOW_OVERLAP,
            "The trip window overlaps an interval already occupied by the selected driver.",
        )

    trip = services.create_trip(rr, scheduled_date, start, end, district_version_bump=False)
    trip["candidate_driver_id"] = candidate["id"] if candidate else None
    rr["status"] = "SCHEDULED"
    rr["recurring_series_active"] = False
    db.bump_version(rr)
    if district:
        calc.recompute_district(district)
        db.bump_version(district)
    # One-off scheduling generates freshly created trips, so the creation code
    # is 201 — the same code the create-trip operation carries.
    return array_response(models.serialise_all("trips", [trip]), status=201)


@bp.post("/student-rides/ride-requests/<rr_id>/suspend-series")
@requires("DistrictAdmin", "PlatformAdmin")
def suspend_series(rr_id):
    rr = load_ride_request(rr_id)
    _state_gate(rr["status"], "SCHEDULED", "Only a SCHEDULED ride request may have its series suspended.")
    if not rr["is_recurring"]:
        raise ApiError(ERR_NOT_RECURRING, "The ride request is not a recurring series.")
    if any(
        t["ride_request_id"] == rr["id"] and t["trip_state"] in ("STUDENT_ONBOARD", "IN_TRANSIT")
        for t in db.all_of("trips")
    ):
        raise ApiError(ERR_TRIP_IN_PROGRESS, "A trip in the series is currently in progress.")

    rr["status"] = "SERIES_SUSPENDED"
    rr["recurring_series_active"] = False
    db.bump_version(rr)

    district = db.get("districts", rr["district_id"])
    for trip in db.all_of("trips"):
        if trip["ride_request_id"] != rr["id"]:
            continue
        if trip["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
            continue
        trip["trip_state"] = "CANCELLED"
        trip["candidate_driver_id"] = None
        trip["driver_id"] = None
        trip["safety_state"] = "NORMAL"
        db.bump_version(trip)
    if district:
        calc.recompute_district(district)
        db.bump_version(district)
    return object_response(models.ride_request_out(rr))


@bp.post("/student-rides/ride-requests/<rr_id>/resume-series")
@requires("DistrictAdmin", "PlatformAdmin")
def resume_series(rr_id):
    rr = load_ride_request(rr_id)
    _state_gate(rr["status"], "SERIES_SUSPENDED", "Only a SERIES_SUSPENDED request may be resumed.")
    if rr.get("series_through_date") and clock_date() > parse_date(rr["series_through_date"]):
        raise ApiError(ERR_SERIES_ENDED, "The series through_date has already passed.")

    iso_dates = calc.recurring_allocation_dates(rr)
    if not iso_dates:
        raise ApiError(
            ERR_NO_SCHOOL_DAYS_IN_RANGE,
            "The recurring series produces zero included dates over its window.",
        )
    windows = services.build_trip_windows(rr, iso_dates)

    for (iso, start, end) in windows:
        d = parse_date(iso)
        candidate = calc.dispatch_rank(rr, d)
        if candidate is None:
            raise ApiError(ERR_NO_ELIGIBLE_DRIVER, "No eligible driver exists for at least one required date.")
        if services.driver_series_overlap(rr, [(start, end)], candidate):
            raise ApiError(ERR_DRIVER_WINDOW_OVERLAP, "A generated trip window overlaps the selected driver's occupancy.")

    created = []
    for (iso, start, end) in windows:
        d = parse_date(iso)
        candidate = calc.dispatch_rank(rr, d)
        trip = services.create_trip(rr, iso, start, end, district_version_bump=False)
        trip["candidate_driver_id"] = candidate["id"] if candidate else None
        created.append(trip)
    # A resumed series may restore a date its suspension had released, but the
    # rider's own closed-interval geometry must still hold.
    conflicts = [
        t for t in db.all_of("trips")
        if t["rider_id"] == rr["rider_id"]
        and t["ride_request_id"] != rr["id"]
        and t["trip_state"] not in ("COMPLETED", "CANCELLED")
    ]
    for (iso, start, end) in windows:
        for t in conflicts:
            other_start = services.trip_window_instant(t["window_start_at"])
            other_end = services.trip_window_instant(t["window_end_at"])
            if calc.closed_overlap(start, end, other_start, other_end):
                for trip in created:
                    db.STORE.trips.pop(trip["id"], None)
                raise ApiError(
                    ERR_RIDER_WINDOW_OVERLAP,
                    "A generated trip window touches or overlaps an existing trip window for this student.",
                )

    rr["status"] = "SCHEDULED"
    rr["recurring_series_active"] = True
    db.bump_version(rr)
    district = db.get("districts", rr["district_id"])
    if district:
        calc.recompute_district(district)
        db.bump_version(district)
    # Resume is a state transition on an existing request, so it returns 200.
    return array_response(models.serialise_all("trips", created), status=200)