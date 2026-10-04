"""Remote assistance sessions and incident reports.

Incidents hang off the assistance session rather than the ride: filing is
accepted only while a session for the ride is still ESCALATED or ACKNOWLEDGED
(PRD 3.5).  Retention is computed in exact seconds from the report's own
severity and creation instant.
"""

from flask import Blueprint, request

from db import store
from errors import fail
from middleware import (
    FLEET_OPERATIONS,
    REMOTE_ASSISTANCE_OPERATOR,
    SAFETY_REVIEWER,
    authorize,
    authenticate,
    body_object,
    get_or_404,
    require_enum,
    require_str,
)
from response import paginate, success_array, success_object
from services import calculations as calc

bp = Blueprint("assistance", __name__)

SESSION_REASONS = ("STUCK", "ROAD_BLOCKED", "SENSOR_FAULT", "PASSENGER_ASSIST", "OTHER")
SEVERITIES = ("MINOR", "MODERATE", "SEVERE")


def _resolve(allowed):
    caller = authenticate(request.headers)
    authorize(caller, allowed)
    return caller


# ─── AssistanceSession ────────────────────────────────────────────────────


@bp.post("/fleet/territories/<territory_id>/ride-requests/<ride_id>/assistance-sessions")
def create_assistance_session(territory_id, ride_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR, FLEET_OPERATIONS))
    get_or_404(store.territories, territory_id)
    ride = get_or_404(store.rides, ride_id)
    if ride["territory_id"] != territory_id:
        raise fail("ERR_NOT_FOUND")
    body = body_object(request.get_json(silent=True))
    reason = require_enum(body, "reason", SESSION_REASONS)

    session = {
        "id": store.new_id(),
        "ride_request_id": ride_id,
        "vehicle_id": ride.get("vehicle_id"),
        "reason": reason,
        "status": "ESCALATED",
        "escalation_tier": 1,
        "attempt_count": 0,
        "op_user_id": None,
        "last_ops_run_index": _observed_epoch(ride),
        "version": 1,
    }
    store.stamp_create(session)
    store.assistance_sessions[session["id"]] = session

    # Escalation records a dispatch attempt against the ride.
    ride["dispatch_attempts"] = ride["dispatch_attempts"] + 1
    store.touch(ride)
    if ride["status"] == "MATCHED" and ride["dispatch_attempts"] >= calc.MAX_SESSION_ATTEMPTS:
        _unwind_dispatch(ride, body.get("credit_cents"))

    return success_object(session, 201)


def _observed_epoch(ride):
    """The operations epoch of the depot servicing the ride's vehicle."""
    vehicle = store.vehicles.get(ride.get("vehicle_id"))
    if vehicle is not None and vehicle.get("current_depot_id"):
        depot = store.depots.get(vehicle["current_depot_id"])
        if depot is not None:
            return depot["ops_run_index"]
    for depot in store.depots.values():
        if depot["territory_id"] == ride["territory_id"]:
            return depot["ops_run_index"]
    return 0


def _unwind_dispatch(ride, credit_cents):
    """Cyclic re-dispatch: un-match the ride and debit the failed vehicle."""
    vehicle = store.vehicles.get(ride["vehicle_id"])
    if vehicle is not None:
        debit = credit_cents if isinstance(credit_cents, int) and not isinstance(credit_cents, bool) else 0
        if debit > 0:
            vehicle["credit_cents"] = max(0, vehicle["credit_cents"] - debit)
            store.touch(vehicle)
            calc.recompute_service_status(vehicle, bump=False)
        else:
            calc.recompute_service_status(vehicle)
    ride["vehicle_id"] = None
    ride["status"] = "REQUESTED"
    store.touch(ride)


@bp.get("/fleet/assistance-sessions")
def list_assistance_sessions():
    _resolve((REMOTE_ASSISTANCE_OPERATOR, FLEET_OPERATIONS, SAFETY_REVIEWER))
    rows = sorted(store.assistance_sessions.values(), key=lambda row: (row["created_at"], row["id"]))
    for param, field in (
        ("status", "status"),
        ("ride_request_id", "ride_request_id"),
        ("vehicle_id", "vehicle_id"),
    ):
        raw = request.args.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/assistance-sessions/<session_id>")
def get_assistance_session(session_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR, FLEET_OPERATIONS, SAFETY_REVIEWER))
    return success_object(get_or_404(store.assistance_sessions, session_id))


@bp.get("/fleet/ride-requests/<ride_id>/assistance-sessions")
def list_ride_assistance_sessions(ride_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR, FLEET_OPERATIONS, SAFETY_REVIEWER))
    get_or_404(store.rides, ride_id)
    rows = sorted(
        (row for row in store.assistance_sessions.values() if row["ride_request_id"] == ride_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/vehicles/<vehicle_id>/assistance-sessions")
def list_vehicle_assistance_sessions(vehicle_id):
    _resolve((FLEET_OPERATIONS, REMOTE_ASSISTANCE_OPERATOR, SAFETY_REVIEWER))
    get_or_404(store.vehicles, vehicle_id)
    rows = sorted(
        (row for row in store.assistance_sessions.values() if row["vehicle_id"] == vehicle_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.post("/fleet/assistance-sessions/<session_id>/acknowledge")
def acknowledge_session(session_id):
    caller = _resolve((REMOTE_ASSISTANCE_OPERATOR,))
    session = get_or_404(store.assistance_sessions, session_id)
    if session["status"] != "ESCALATED":
        raise fail("ERR_INVALID_STATE")
    session["status"] = "ACKNOWLEDGED"
    session["op_user_id"] = caller.user_id
    store.touch(session)
    return success_object(session)


@bp.post("/fleet/assistance-sessions/<session_id>/resolve")
def resolve_session(session_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR,))
    session = get_or_404(store.assistance_sessions, session_id)
    if session["status"] != "ACKNOWLEDGED":
        raise fail("ERR_INVALID_STATE")
    session["status"] = "RESOLVED"
    store.touch(session)
    return success_object(session)


@bp.post("/fleet/assistance-sessions/<session_id>/escalate-unresolved")
def escalate_session_unresolved(session_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR,))
    session = get_or_404(store.assistance_sessions, session_id)
    if session["status"] != "ACKNOWLEDGED":
        raise fail("ERR_INVALID_STATE")
    if session["attempt_count"] < calc.MAX_SESSION_ATTEMPTS:
        raise fail("ERR_MAX_ATTEMPTS_NOT_REACHED")
    session["status"] = "UNRESOLVED"
    store.touch(session)

    # Cascade: the referencing ride FAILS, which recomputes the vehicle.
    ride = store.rides.get(session["ride_request_id"])
    if ride is not None and ride["status"] != "FAILED":
        ride["status"] = "FAILED"
        store.touch(ride)
        vehicle = store.vehicles.get(ride.get("vehicle_id"))
        if vehicle is not None:
            calc.recompute_service_status(vehicle)
    return success_object(session)


# ─── IncidentReport ───────────────────────────────────────────────────────


@bp.post("/fleet/ride-requests/<ride_id>/film-incident")
def film_incident(ride_id):
    _resolve((REMOTE_ASSISTANCE_OPERATOR, SAFETY_REVIEWER))
    ride = get_or_404(store.rides, ride_id)
    body = body_object(request.get_json(silent=True))
    severity = require_enum(body, "severity", SEVERITIES)
    description = require_str(body, "description")

    session = _open_session_for_ride(ride_id)
    if session is None:
        raise fail("ERR_SESSION_TERMINAL")

    report = {
        "id": store.new_id(),
        "assistance_session_id": session["id"],
        "vehicle_id": session["vehicle_id"] if session["vehicle_id"] else ride.get("vehicle_id"),
        "severity": severity,
        "description": description,
        "status": "FILED",
        "version": 1,
    }
    store.stamp_create(report)
    report["crash_evidence_retained"] = severity in ("MODERATE", "SEVERE")
    report["retention_expires_at"] = _retention_expiry(report)
    store.incident_reports[report["id"]] = report

    vehicle = store.vehicles.get(report["vehicle_id"])
    territory = store.territories.get(vehicle["territory_id"]) if vehicle else None
    if territory is not None:
        calc.recompute_total_severe_incidents(territory, report["vehicle_id"])
    return success_object(report, 201)


def _open_session_for_ride(ride_id):
    """The ride's session that is still ESCALATED or ACKNOWLEDGED, if any."""
    for session in store.assistance_sessions.values():
        if session["ride_request_id"] != ride_id:
            continue
        if session["status"] in ("ESCALATED", "ACKNOWLEDGED"):
            return session
    return None


def _retention_expiry(report):
    import datetime as dt

    from db import format_utc

    created = calc._instant(report["created_at"])
    days = calc.CRASH_RETENTION_DAYS if report["crash_evidence_retained"] else calc.STANDARD_RETENTION_DAYS
    return format_utc(created + dt.timedelta(seconds=days * calc.SECONDS_PER_DAY))


@bp.get("/fleet/incident-reports")
def list_incident_reports():
    _resolve((SAFETY_REVIEWER, FLEET_OPERATIONS))
    rows = sorted(store.incident_reports.values(), key=lambda row: (row["created_at"], row["id"]))
    for param, field in (
        ("status", "status"),
        ("assistance_session_id", "assistance_session_id"),
        ("vehicle_id", "vehicle_id"),
    ):
        raw = request.args.get(param)
        if raw:
            rows = [row for row in rows if row.get(field) == raw]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.get("/fleet/incident-reports/<incident_id>")
def get_incident_report(incident_id):
    _resolve((SAFETY_REVIEWER, FLEET_OPERATIONS))
    return success_object(get_or_404(store.incident_reports, incident_id))


@bp.get("/fleet/assistance-sessions/<session_id>/incident-reports")
def list_session_incident_reports(session_id):
    _resolve((SAFETY_REVIEWER, FLEET_OPERATIONS))
    get_or_404(store.assistance_sessions, session_id)
    rows = sorted(
        (row for row in store.incident_reports.values() if row["assistance_session_id"] == session_id),
        key=lambda row: (row["created_at"], row["id"]),
    )
    page, limit, offset, total = paginate(rows, request.args)
    return success_array(page, limit, offset, total)


@bp.post("/fleet/incident-reports/<incident_id>/begin-review")
def begin_incident_review(incident_id):
    _resolve((SAFETY_REVIEWER,))
    report = get_or_404(store.incident_reports, incident_id)
    if report["status"] != "FILED":
        raise fail("ERR_INVALID_STATE")
    report["status"] = "UNDER_REVIEW"
    store.touch(report)
    _refresh_severe_count(report)
    return success_object(report)


@bp.post("/fleet/incident-reports/<incident_id>/close")
def close_incident_report(incident_id):
    _resolve((SAFETY_REVIEWER,))
    report = get_or_404(store.incident_reports, incident_id)
    if report["status"] != "UNDER_REVIEW":
        raise fail("ERR_INVALID_STATE")
    report["status"] = "CLOSED"
    store.touch(report)
    return success_object(report)


@bp.post("/fleet/incident-reports/<incident_id>/void")
def void_incident_report(incident_id):
    _resolve((SAFETY_REVIEWER,))
    report = get_or_404(store.incident_reports, incident_id)
    if report["status"] != "FILED":
        raise fail("ERR_INVALID_STATE")
    report["status"] = "VOIDED"
    store.touch(report)
    _refresh_severe_count(report)
    return success_object(report)


def _refresh_severe_count(report):
    vehicle = store.vehicles.get(report["vehicle_id"])
    if vehicle is None:
        return
    territory = store.territories.get(vehicle["territory_id"])
    if territory is not None:
        calc.recompute_total_severe_incidents(territory, report["vehicle_id"])