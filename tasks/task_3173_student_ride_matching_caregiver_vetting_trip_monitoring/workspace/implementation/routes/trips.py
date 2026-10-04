"""Trip endpoints: creation, dispatch, movement, handoffs, exceptions, posture
recovery, monitoring observations and the refund cycle.

Transcribed from SCAFFOLD.yaml section 1.2 (Trip compound state machine) and
PRD sections 2.5, 2.6, 3.6, 3.8 and 3.9.
"""

import calculations as calc
import db
import models
import services
import validators as v
from clock import now_utc, parse_date, stamp
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_DUPLICATE_CLEARANCE,
    ERR_DRIVER_INELIGIBLE,
    ERR_DRIVER_NOT_SELECTED,
    ERR_HANDOFF_ALREADY_ATTEMPTED,
    ERR_HANDOFF_NOT_AUTHORIZED,
    ERR_INCIDENT_ALREADY_REPORTED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NO_ELIGIBLE_DRIVER,
    ERR_NOT_TRIP_DRIVER,
    ERR_OPEN_ALERTS,
    ERR_REQUEST_NOT_SCHEDULED,
    ERR_RIDER_WINDOW_OVERLAP,
    ERR_TRIP_ALREADY_CLAIMED,
    ERR_TRIP_DISCREPANCY_LOCK,
    ERR_TRIP_IN_PAST,
    ERR_WAIT_TIME_NOT_MET,
    ERR_STALE_VERSION,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import actor_id, actor_role, requires
from response import array_response, object_response, paginate

bp = Blueprint("trips", __name__)

TRIP_INPUT = (
    "expected_district_version", "ride_request_id", "scheduled_date",
    "window_start_at", "window_end_at", "planned_miles",
)
HANDOFF_INPUT = (
    "leg", "expected_party", "verified_party_name", "verification_method",
    "verification_code", "billable_miles",
)
EXCEPTION_INPUT = ("issue", "note")
GEOFENCE_CHECK_INPUT = ("observed_at", "observed_lat", "observed_lon")

TERMINAL_TRIP_STATES = ("COMPLETED", "CANCELLED")


def load_trip(trip_id):
    trip = db.get("trips", trip_id)
    if trip is None:
        raise not_found("The addressed trip does not exist.")
    return trip


def _terminal_gate(trip, allowed_terminal=()):
    """A resource already terminal for the trip_state dimension reports
    ERR_ALREADY_TERMINAL rather than the ordinary wrong-state error."""
    if trip["trip_state"] in TERMINAL_TRIP_STATES and trip["trip_state"] not in allowed_terminal:
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The trip has already reached a terminal state for the movement dimension.",
        )


def _posture_gate(trip):
    if trip["safety_state"] != "NORMAL":
        raise ApiError(
            ERR_TRIP_DISCREPANCY_LOCK,
            "The trip's safety posture is DISCREPANCY or LOCKED; the transition is refused.",
        )


def _state_gate(trip, required, msg, allowed_terminal=()):
    if isinstance(required, str):
        required = (required,)
    _terminal_gate(trip, allowed_terminal=allowed_terminal)
    if trip["trip_state"] not in required:
        raise ApiError(ERR_INVALID_STATE, msg)


def _driver_match(trip, required=True):
    """Driver-scoped actions require X-User-ID to equal trip.driver_id.

    PRD section 3: the driver-scoped identity check is an authorisation rule, so
    it is settled before any of the operation's own business checks - a caller
    who is not the trip's driver never learns whether the later gates passed.
    """
    if actor_role() != "Driver":
        if required:
            raise ApiError(ERR_NOT_TRIP_DRIVER, "This action is scoped to the trip's assigned driver.")
        return
    if actor_id() != trip.get("driver_id"):
        raise ApiError(ERR_NOT_TRIP_DRIVER, "X-User-ID is not the driver assigned to this trip.")


def _guard(trip, required_states=None, msg=None, driver_match=True, allowed_terminal=()):
    """Run the trip gates in their settled order.

    auth (driver-scoped identity) -> posture (priority 4) -> state (priority 9).
    PRD section 3 fixes this order so that a locked trip reports a discrepancy
    lock rather than a wrong-state error.
    """
    if driver_match:
        _driver_match(trip)
    _posture_gate(trip)
    if required_states is not None:
        _terminal_gate(trip, allowed_terminal=allowed_terminal)
        if isinstance(required_states, str):
            required_states = (required_states,)
        if trip["trip_state"] not in required_states:
            raise ApiError(ERR_INVALID_STATE, msg)


# --- Creation ----------------------------------------------------------------

@bp.post("/student-rides/trips")
@requires("DistrictAdmin", "PlatformAdmin")
def create_trip():
    data = v.body()
    v.reject_unknown(data, TRIP_INPUT)
    rr_id = v.as_string(data, "ride_request_id")
    rr = db.get("ride_requests", rr_id)
    if rr is None:
        raise not_found("The addressed ride request does not exist.")

    district = db.get("districts", rr["district_id"])
    if district is None:
        raise not_found("The addressed district does not exist.")

    # OCC against the receiving district.
    from routes.districts import check_stale
    check_stale(district, data)

    if rr["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_STATE,
            "A trip may only be created directly against a SCHEDULED ride request.",
        )

    scheduled_date = v.as_iso_date_string(data, "scheduled_date")
    window_start = v.as_iso_dt(data, "window_start_at")
    window_end = v.as_iso_dt(data, "window_end_at")
    if not window_start < window_end:
        raise ApiError(ERR_INVALID_REQUEST, "window_start_at must fall strictly before window_end_at.")

    for existing in db.all_of("trips"):
        if existing["ride_request_id"] == rr["id"] and existing["scheduled_date"] == scheduled_date:
            raise ApiError(
                ERR_INVALID_STATE,
                "A trip already exists for this ride request and scheduled date.",
            )

    if services.rider_window_collision(rr["rider_id"], [(window_start, window_end)]):
        raise ApiError(
            ERR_RIDER_WINDOW_OVERLAP,
            "The trip window touches or overlaps an existing trip window for this student.",
        )

    trip = services.create_trip(
        rr, scheduled_date, window_start, window_end,
        planned_miles=v.as_number(data, "planned_miles", default=None),
    )
    return object_response(models.trip_out(trip), 201)


@bp.get("/student-rides/trips/<trip_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def get_trip(trip_id):
    return object_response(models.trip_out(load_trip(trip_id)))


@bp.get("/student-rides/trips/<trip_id>/alerts")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def list_trip_alerts(trip_id):
    load_trip(trip_id)
    rows = [a for a in db.all_of("trip_alerts") if a["trip_id"] == trip_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("trip_alerts", page), limit, offset, total)


@bp.get("/student-rides/trips/<trip_id>/handoffs")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def list_trip_handoffs(trip_id):
    load_trip(trip_id)
    rows = [h for h in db.all_of("handoffs") if h["trip_id"] == trip_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("handoffs", page), limit, offset, total)


@bp.get("/student-rides/trips/<trip_id>/safety-incidents")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def list_trip_incidents(trip_id):
    load_trip(trip_id)
    rows = [i for i in db.all_of("safety_incidents") if i["trip_id"] == trip_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("safety_incidents", page), limit, offset, total)


@bp.get("/student-rides/trips/<trip_id>/geofence-checks")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent", "Driver")
def list_trip_geofence_checks(trip_id):
    load_trip(trip_id)
    rows = [g for g in db.all_of("geofence_checks") if g["trip_id"] == trip_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("geofence_checks", page), limit, offset, total)


# --- Dispatch and movement ---------------------------------------------------

@bp.post("/student-rides/trips/<trip_id>/dispatch-candidate")
@requires("DistrictAdmin", "PlatformAdmin")
def dispatch_candidate(trip_id):
    trip = load_trip(trip_id)
    _terminal_gate(trip)
    _posture_gate(trip)
    rr = db.get("ride_requests", trip["ride_request_id"])
    if rr is None:
        raise not_found("The trip's parent ride request no longer exists.")
    d = parse_date(trip["scheduled_date"])
    candidate = calc.dispatch_rank(rr, d, exclude_trip_id=trip["id"])
    if candidate is None:
        raise ApiError(ERR_NO_ELIGIBLE_DRIVER, "No eligible driver exists for this trip's date.")
    trip["candidate_driver_id"] = candidate["id"]
    db.bump_version(trip)
    return object_response(models.trip_out(trip))


@bp.post("/student-rides/trips/<trip_id>/accept")
@requires("Driver", "DistrictAdmin")
def accept_trip(trip_id):
    trip = load_trip(trip_id)

    # Authorisation first (PRD section 3): the candidate-selection check is a
    # driver-scoped check on the acting identity, so a caller who is not the
    # pinned driver never learns whether the trip's later gates would have
    # passed. A DistrictAdmin acting on the driver's behalf skips it.
    if actor_role() == "Driver":
        if trip.get("candidate_driver_id") is None or actor_id() != trip["candidate_driver_id"]:
            raise ApiError(
                ERR_DRIVER_NOT_SELECTED,
                "X-User-ID is not the driver pinned as this trip's dispatch candidate.",
            )

    _posture_gate(trip)
    _state_gate(trip, "SCHEDULED", "Only a SCHEDULED trip may be accepted.")
    if trip.get("driver_id") is not None:
        raise ApiError(ERR_TRIP_ALREADY_CLAIMED, "The trip already carries a driver.")

    if actor_role() == "Driver":
        # Candidate freshness is re-checked at accept time.
        driver = db.get("drivers", actor_id())
        rr = db.get("ride_requests", trip["ride_request_id"])
        if (rr is None
                or not calc.driver_eligible(driver, rr, parse_date(trip["scheduled_date"]))):
            raise ApiError(
                ERR_DRIVER_INELIGIBLE,
                "The pinned candidate no longer satisfies the full eligibility filter.",
            )
    else:
        driver = db.get("drivers", trip.get("candidate_driver_id")) if trip.get("candidate_driver_id") else None

    accepting_driver_id = actor_id() if actor_role() == "Driver" else trip.get("candidate_driver_id")
    trip["trip_state"] = "DRIVER_EN_ROUTE"
    trip["driver_id"] = accepting_driver_id
    trip["claimed_by_user_id"] = accepting_driver_id
    trip["accepted_at"] = stamp()
    db.bump_version(trip)

    if driver is not None:
        db.bump_version(driver)
    services.refresh_trip_relations(trip)
    return object_response(models.trip_out(trip))


@bp.post("/student-rides/trips/<trip_id>/arrive")
@requires("Driver")
def arrive(trip_id):
    trip = load_trip(trip_id)
    _guard(trip, "DRIVER_EN_ROUTE", "Only a DRIVER_EN_ROUTE trip may arrive at pickup.")
    trip["trip_state"] = "AWAITING_STUDENT"
    trip["arrived_at"] = stamp()
    db.bump_version(trip)
    return object_response(models.trip_out(trip))


@bp.post("/student-rides/trips/<trip_id>/depart")
@requires("Driver")
def depart(trip_id):
    trip = load_trip(trip_id)
    _guard(trip, "STUDENT_ONBOARD", "Only a STUDENT_ONBOARD trip may depart.")

    trip["trip_state"] = "IN_TRANSIT"
    db.bump_version(trip)

    # A departure after the window has closed raises a geofence-breach alert.
    if services.trip_window_instant(trip["window_end_at"]) < now_utc():
        services.create_trip_alert(trip, services.ALERT_GEOFENCE_BREACH, source_incident_id=None)
    return object_response(models.trip_out(trip))


# --- Handoffs ----------------------------------------------------------------

@bp.post("/student-rides/trips/<trip_id>/handoffs")
@requires("Driver")
def record_handoff(trip_id):
    trip = load_trip(trip_id)
    data = v.body()
    v.reject_unknown(data, HANDOFF_INPUT)

    leg = v.enum_value("leg", v.required(data, "leg"))
    expected_party = v.enum_value("expected_party", v.required(data, "expected_party"))
    verified_party_name = v.as_string(data, "verified_party_name")
    verification_method = v.enum_value("verification_method", v.required(data, "verification_method"))
    verification_code = v.as_string(data, "verification_code", required_field=False)
    billable_miles = v.as_number(data, "billable_miles", default=None)

    existing = [h for h in db.all_of("handoffs") if h["trip_id"] == trip_id]
    # At most two handoff attempts in the relevant sense (PRD section 3.8).
    if leg == "PICKUP" and any(h["leg"] == "PICKUP" for h in existing):
        raise ApiError(ERR_HANDOFF_ALREADY_ATTEMPTED, "A pickup handoff already exists on this trip.")
    if leg == "DROPOFF" and any(h["leg"] == "DROPOFF" and h["result"] == "FAILED" for h in existing):
        raise ApiError(ERR_HANDOFF_ALREADY_ATTEMPTED, "A failed dropoff handoff is already recorded on this trip.")

    _posture_gate(trip)
    _driver_match(trip)
    if leg == "PICKUP":
        _state_gate(trip, "AWAITING_STUDENT", "A pickup handoff requires the trip to be AWAITING_STUDENT.")
    else:
        _state_gate(trip, "IN_TRANSIT", "A dropoff handoff requires the trip to be IN_TRANSIT.")

    rider = db.get("riders", trip["rider_id"])
    if rider is None:
        raise not_found("The trip's rider no longer exists.")

    authorized = calc.handoff_verification_authorization(
        leg, expected_party, verified_party_name, verification_method, verification_code, rider,
    )
    handoff = db.new_record({
        "trip_id": trip_id,
        "leg": leg,
        "expected_party": expected_party,
        "verified_party_name": verified_party_name,
        "verification_method": verification_method,
        "verification_code": verification_code,
        "authorized": authorized,
        "result": "PASSED" if authorized else "FAILED",
        "captured_at": stamp(),
    })
    db.save("handoffs", handoff)

    if leg == "PICKUP":
        if authorized:
            trip["trip_state"] = "STUDENT_ONBOARD"
            trip["verified_by_user_id"] = actor_id()
            db.bump_version(trip)
            services.refresh_trip_relations(trip)
            # rider.notify_on_pickup true dispatches a notice; false emits nothing.
        else:
            db.bump_version(trip)
            services.create_trip_alert(trip, services.ALERT_STUDENT_ABSENT, source_incident_id=None)
            raise ApiError(
                ERR_HANDOFF_NOT_AUTHORIZED,
                "The named party is not an authorised releasing party for this pickup.",
            )
        return object_response(models.handoff_out(handoff), 201)

    # DROPOFF
    if billable_miles is not None:
        trip["billable_miles"] = billable_miles
    if authorized:
        trip["trip_state"] = "COMPLETED"
        trip["verified_by_user_id"] = actor_id()
        trip["verified_authorized_adult_name"] = verified_party_name
        services.finalize_trip_completion(trip)
        db.bump_version(trip)
        services.refresh_trip_relations(trip)
        return object_response(models.handoff_out(handoff), 201)

    # A failing dropoff still completes the trip, but penalises it.
    trip["trip_state"] = "COMPLETED"
    trip["verified_by_user_id"] = actor_id()
    services.finalize_trip_completion(trip)
    trip["safety_state"] = "DISCREPANCY"
    trip["exception_code"] = "UNAUTHORIZED_DROPOFF"
    trip["exception_recorded_at"] = stamp()
    db.bump_version(trip)
    services.refresh_trip_relations(trip)
    services.create_trip_alert(trip, services.ALERT_HANDOFF_DISPUTE, source_incident_id=None)
    dispute = services.create_safety_incident(
        trip, "HANDOFF_DISPUTE", "MEDIUM",
        reported_by_actor=actor_id(),
        summary="Dropoff verification named a party who is not authorised to receive the student.",
    )
    # The dispute alert is anchored to the dispute incident, so reviewing the
    # incident closes it.
    for alert in db.all_of("trip_alerts"):
        if (alert["trip_id"] == trip_id and alert["alert_type"] == services.ALERT_HANDOFF_DISPUTE
                and alert["source_incident_id"] is None):
            alert["source_incident_id"] = dispute["id"]
    raise ApiError(
        ERR_HANDOFF_NOT_AUTHORIZED,
        "The named party is not the school of record and does not appear in the student's authorised adults.",
    )


# --- Absence reporting -------------------------------------------------------

@bp.post("/student-rides/trips/<trip_id>/exceptions")
@requires("Driver")
def report_exception(trip_id):
    trip = load_trip(trip_id)
    data = v.body()
    v.reject_unknown(data, EXCEPTION_INPUT)

    # A second report is refused even though the trip is already cancelled.
    if any(i["trip_id"] == trip_id and i["category"] == "NO_SHOW_UNVERIFIED"
           for i in db.all_of("safety_incidents")):
        raise ApiError(
            ERR_INCIDENT_ALREADY_REPORTED,
            "An absence incident has already been recorded for this trip.",
        )

    issue = v.required(data, "issue")
    if issue not in ("RIDER_NOT_PRESENT", "RIDER_REFUSED_BOARDING"):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "issue must be RIDER_NOT_PRESENT or RIDER_REFUSED_BOARDING.",
        )
    note = v.as_string(data, "note", required_field=False)

    _guard(trip, "AWAITING_STUDENT", "An absence may only be reported while the trip is AWAITING_STUDENT.")

    if calc.wait_time_block_units(trip) < calc.WAIT_TIME_MIN_BLOCKS:
        raise ApiError(
            ERR_WAIT_TIME_NOT_MET,
            "The accrued wait time has not yet reached the two-block minimum.",
        )

    rider = db.get("riders", trip["rider_id"])
    if rider is None:
        raise not_found("The trip's rider no longer exists.")

    points, grade = calc.student_absence_grade_points(trip, rider)

    trip["trip_state"] = "CANCELLED"
    trip["exception_code"] = issue
    trip["exception_recorded_at"] = stamp()
    services.apply_grade_posture(trip, grade)
    db.bump_version(trip)

    # The alert is anchored to the incident it was spawned by, so a later
    # incident review closes it.
    incident = services.create_safety_incident(
        trip, "NO_SHOW_UNVERIFIED", grade,
        reported_by_actor=actor_id(),
        summary=note,
    )
    services.create_trip_alert(
        trip, services.ALERT_STUDENT_ABSENT, source_incident_id=incident["id"],
        severity_override=grade,
    )
    services.refresh_trip_relations(trip)

    if grade == "HIGH":
        driver = db.get("drivers", trip["driver_id"]) if trip.get("driver_id") else None
        if driver is not None:
            calc.recompute_driver(driver)
            calc.maybe_suspend_driver(driver)
    return object_response(models.trip_out(trip), 201)


# --- Planned cancellation and restoration -----------------------------------

@bp.post("/student-rides/trips/<trip_id>/cancel")
@requires("DistrictAdmin", "PlatformAdmin")
def cancel_trip(trip_id):
    trip = load_trip(trip_id)
    data = v.body()
    v.reject_unknown(data, ("reason",))
    # PRD §3.8 makes SCHEDULED the only cancellable movement state and reads a
    # COMPLETED or CANCELLED trip as the ordinary wrong-state refusal — "a trip
    # in any other movement state is refused with `ERR_INVALID_STATE` (HTTP
    # 409)". It therefore compresses the two terminal states into the same
    # wrong-state answer rather than treating a completed trip as a terminal
    # probe.
    if trip["trip_state"] not in ("SCHEDULED",):
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a SCHEDULED trip may be cancelled.",
        )
    if trip["safety_state"] != "NORMAL":
        raise ApiError(
            ERR_TRIP_DISCREPANCY_LOCK,
            "The trip's safety posture is DISCREPANCY or LOCKED; the transition is refused.",
        )

    trip["trip_state"] = "CANCELLED"
    db.bump_version(trip)
    services.refresh_trip_relations(trip)
    return object_response(models.trip_out(trip))


@bp.post("/student-rides/trips/<trip_id>/restore")
@requires("DistrictAdmin", "PlatformAdmin")
def restore_trip(trip_id):
    trip = load_trip(trip_id)
    # PRD §3.8 makes CANCELLED the only legal source state and the parent
    # request's own state the gate: "a `DistrictAdmin` may return a `CANCELLED`
    # trip to `SCHEDULED`, but only while the parent request is still
    # `SCHEDULED` — otherwise the attempt is refused with
    # `ERR_REQUEST_NOT_SCHEDULED`". A parent-gate refusal is evaluated ahead of
    # the terminal-movement-probe special case, so a suspended series reports
    # the parent's refusal rather than ERR_ALREADY_TERMINAL.
    if trip["trip_state"] != "CANCELLED":
        _state_gate(trip, "CANCELLED", "Only a CANCELLED trip may be restored.")

    rr = db.get("ride_requests", trip["ride_request_id"])
    if rr is None or rr["status"] != "SCHEDULED":
        raise ApiError(
            ERR_REQUEST_NOT_SCHEDULED,
            "The parent ride request is not in SCHEDULED status.",
        )
    if parse_date(trip["scheduled_date"]) < now_utc().date():
        raise ApiError(ERR_TRIP_IN_PAST, "A trip may not be restored into the past.")
    if trip["safety_state"] != "NORMAL":
        raise ApiError(
            ERR_TRIP_DISCREPANCY_LOCK,
            "A trip whose absence still grades MEDIUM or HIGH cannot be restored.",
        )

    trip["trip_state"] = "SCHEDULED"
    trip["driver_id"] = None
    trip["claimed_by_user_id"] = None
    trip["candidate_driver_id"] = None
    trip["accepted_at"] = None
    trip["arrived_at"] = None
    trip["exception_code"] = None
    trip["exception_recorded_at"] = None
    db.bump_version(trip)
    services.refresh_trip_relations(trip)
    return object_response(models.trip_out(trip))


# --- Posture recovery --------------------------------------------------------

@bp.post("/student-rides/trips/<trip_id>/resolve-discrepancy")
@requires("SupportCenterAgent", "PlatformAdmin")
def resolve_discrepancy(trip_id):
    trip = load_trip(trip_id)
    if trip["safety_state"] == "DISCREPANCY":
        if trip["trip_state"] != "COMPLETED":
            raise ApiError(
                ERR_INVALID_STATE,
                "A discrepancy may only be cleared once the trip has completed.",
            )
        trip["safety_state"] = "NORMAL"
        # PRD §3.9: clearing "also clears the trip's exception code and the
        # instant it was recorded" — this is the hop that clears the exception.
        trip["exception_code"] = None
        trip["exception_recorded_at"] = None
    elif trip["safety_state"] == "LOCKED":
        open_alerts = [
            a for a in db.all_of("trip_alerts")
            if a["trip_id"] == trip_id and a["status"] == "OPEN"
        ]
        if open_alerts:
            raise ApiError(ERR_OPEN_ALERTS, "The trip still carries open alerts.")
        # PRD §2.5: "the same action against a locked trip moves it only as far
        # as `DISCREPANCY`". The exception record is NOT cleared here, because
        # PRD gates trip restoration on the absence grade: "A trip cancelled
        # because its student never boarded cannot be restored while the absence
        # still grades `MEDIUM` or `HIGH`, because that grade leaves the trip's
        # posture away from `NORMAL`." Releasing the exception at this hop would
        # erase the reference needed to keep that grade observable.
        trip["safety_state"] = "DISCREPANCY"
    else:
        raise ApiError(ERR_INVALID_STATE, "The trip is not in a degraded safety posture.")

    # billable_ride_units is deliberately NOT recomputed here.
    db.bump_version(trip)
    return object_response(models.trip_out(trip))


@bp.post("/student-rides/trips/<trip_id>/release-lock")
@requires("PlatformAdmin")
def release_lock(trip_id):
    trip = load_trip(trip_id)
    # PRD §2.5 reads the release as the completion of the two-hop recovery: a
    # trip in `LOCKED` can reach `NORMAL` this way, and the same operation then
    # carries a trip the discrepancy hop left in `DISCREPANCY` on to `NORMAL`.
    # A trip already at `NORMAL` is the ordinary wrong-state refusal.
    if trip["safety_state"] not in ("LOCKED", "DISCREPANCY"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a LOCKED or DISCREPANCY trip may have its lock released.",
        )
    open_alerts = [
        a for a in db.all_of("trip_alerts")
        if a["trip_id"] == trip_id and a["status"] == "OPEN"
    ]
    if open_alerts:
        raise ApiError(ERR_OPEN_ALERTS, "The trip still carries open alerts.")
    trip["safety_state"] = "NORMAL"
    db.bump_version(trip)
    return object_response(models.trip_out(trip))


# --- Monitoring observations -------------------------------------------------

@bp.post("/student-rides/trips/<trip_id>/geofence-checks")
@requires("SupportCenterAgent", "PlatformAdmin")
def create_geofence_checks(trip_id):
    trip = load_trip(trip_id)
    data = v.body()
    v.reject_unknown(data, GEOFENCE_CHECK_INPUT)
    observed_at = v.as_iso_dt(data, "observed_at")
    observed_lat = v.as_number(data, "observed_lat", required_field=True)
    observed_lon = v.as_number(data, "observed_lon", required_field=True)

    fences = [g for g in db.all_of("geofences") if g["district_id"] == trip["district_id"]]
    created = []
    for fence in fences:
        inside = calc.geofence_containment(observed_lat, observed_lon, fence)
        check = db.new_record({
            "trip_id": trip_id,
            "geofence_id": fence["id"],
            "observed_at": services.fmt_or_none(observed_at),
            "observed_lat": services.num_or_none(observed_lat),
            "observed_lon": services.num_or_none(observed_lon),
            "inside": inside,
            "breach_alert_id": None,
        })
        db.save("geofence_checks", check)
        if not inside and trip["trip_state"] == "IN_TRANSIT":
            alert = services.create_trip_alert(
                trip, services.ALERT_GEOFENCE_BREACH, source_incident_id=None,
            )
            check["breach_alert_id"] = alert["id"]
        created.append(check)
    return array_response(models.serialise_all("geofence_checks", created), status=201)