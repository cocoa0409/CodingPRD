"""SafetyIncident and TripAlert endpoints.

Transcribed from SCAFFOLD.yaml section 1.2 (SafetyIncident and TripAlert
machines) and PRD section 3.9.
"""

import calculations as calc
import db
import models
import services
import validators as v
from clock import now_utc
from errors import (
    ERR_ADJUDICATION_REQUIRED,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_RESOLUTION_NOTE_REQUIRED,
    ERR_SUSPENSION_REQUIRES_FAULT,
    ApiError,
    not_found,
)
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("incidents", __name__)

RESOLVE_INPUT = ("resolution_note", "adjudication")
REOPEN_INPUT = ("reason",)
VOID_INPUT = ("reason",)


def load_incident(incident_id):
    incident = db.get("safety_incidents", incident_id)
    if incident is None:
        raise not_found("The addressed safety incident does not exist.")
    return incident


def load_alert(alert_id):
    alert = db.get("trip_alerts", alert_id)
    if alert is None:
        raise not_found("The addressed trip alert does not exist.")
    return alert


def _state_gate(current, required, msg):
    """A VOIDED incident is terminal, so a later probe reports ERR_ALREADY_TERMINAL."""
    if isinstance(required, str):
        required = (required,)
    if current in required:
        return
    if current == "VOIDED":
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "The incident has already reached its terminal VOIDED state.",
        )
    raise ApiError(ERR_INVALID_STATE, msg)


@bp.get("/student-rides/safety-incidents/<incident_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def get_incident(incident_id):
    incident = load_incident(incident_id)
    driver = db.get("drivers", incident["driver_id"]) if incident.get("driver_id") else None
    incident["student_impact_score"] = calc.safety_incident_impact_score(incident, driver)
    return object_response(models.safety_incident_out(incident))


@bp.get("/student-rides/safety-incidents/<incident_id>/alerts")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_incident_alerts(incident_id):
    load_incident(incident_id)
    rows = [a for a in db.all_of("trip_alerts") if a.get("source_incident_id") == incident_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("trip_alerts", page), limit, offset, total)


@bp.post("/student-rides/safety-incidents/<incident_id>/review")
@requires("SupportCenterAgent", "PlatformAdmin")
def review_incident(incident_id):
    incident = load_incident(incident_id)
    _state_gate(incident["status"], "REPORTED", "Only a REPORTED incident may be moved under review.")
    incident["status"] = "UNDER_REVIEW"
    db.bump_version(incident)
    services.resolve_linked_alerts(incident, released_by_resolution=True)
    return object_response(models.safety_incident_out(incident))


@bp.post("/student-rides/safety-incidents/<incident_id>/resolve")
@requires("SupportCenterAgent", "PlatformAdmin")
def resolve_incident(incident_id):
    incident = load_incident(incident_id)
    data = v.body()
    v.reject_unknown(data, RESOLVE_INPUT)

    _state_gate(
        incident["status"], ("REPORTED", "UNDER_REVIEW"),
        "Only a REPORTED or UNDER_REVIEW incident may be resolved.",
    )

    note = data.get("resolution_note")
    if not isinstance(note, str) or not note.strip():
        raise ApiError(ERR_RESOLUTION_NOTE_REQUIRED, "A non-empty resolution_note is required.")

    adjudication = data.get("adjudication")
    if adjudication not in ("DRIVER_AT_FAULT", "NO_FAULT"):
        raise ApiError(
            ERR_ADJUDICATION_REQUIRED,
            "Resolution requires an adjudication of DRIVER_AT_FAULT or NO_FAULT.",
        )

    driver = db.get("drivers", incident["driver_id"]) if incident.get("driver_id") else None

    if incident["status"] == "REPORTED":
        # An incident resolved at the reported stage may only be not-at-fault.
        if adjudication != "NO_FAULT":
            raise ApiError(
                ERR_ADJUDICATION_REQUIRED,
                "A REPORTED incident may only be resolved with a NO_FAULT adjudication.",
            )
    else:
        if adjudication == "NO_FAULT" and driver is not None:
            if int(driver.get("incident_strike_count") or 0) >= calc.DRIVER_SUSPENSION_STRIKE_THRESHOLD:
                raise ApiError(
                    ERR_SUSPENSION_REQUIRES_FAULT,
                    "A NO_FAULT resolution would lift a suspension this incident did not cause.",
                )

    incident["status"] = "RESOLVED"
    incident["adjudication"] = adjudication
    incident["resolution_note"] = note
    db.bump_version(incident)

    if adjudication == "DRIVER_AT_FAULT" and driver is not None:
        # The third hop of the strike cascade.
        calc.recompute_driver(driver)
        calc.maybe_suspend_driver(driver)
        services.recompute_impact_scores_for_driver(driver["id"])

    incident["student_impact_score"] = calc.safety_incident_impact_score(
        incident, db.get("drivers", incident["driver_id"]) if incident.get("driver_id") else None,
    )
    return object_response(models.safety_incident_out(incident))


@bp.post("/student-rides/safety-incidents/<incident_id>/reopen")
@requires("PlatformAdmin")
def reopen_incident(incident_id):
    incident = load_incident(incident_id)
    data = v.body()
    v.reject_unknown(data, REOPEN_INPUT)
    v.as_string(data, "reason", required_field=False)

    if incident["status"] != "RESOLVED" or incident["adjudication"] != "DRIVER_AT_FAULT":
        _state_gate(
            incident["status"], "RESOLVED",
            "Only a RESOLVED at-fault incident may be reopened.",
        )
        raise ApiError(
            ERR_INVALID_STATE,
            "Only an incident adjudicated DRIVER_AT_FAULT may be reopened.",
        )

    incident["status"] = "UNDER_REVIEW"
    incident["adjudication"] = None
    db.bump_version(incident)

    driver = db.get("drivers", incident["driver_id"]) if incident.get("driver_id") else None
    if driver is not None:
        calc.recompute_driver(driver)
        calc.maybe_reactivate_driver(driver)
        services.recompute_impact_scores_for_driver(driver["id"])
        incident["student_impact_score"] = calc.safety_incident_impact_score(incident, driver)
    return object_response(models.safety_incident_out(incident))


@bp.post("/student-rides/safety-incidents/<incident_id>/void")
@requires("SupportCenterAgent", "PlatformAdmin")
def void_incident(incident_id):
    incident = load_incident(incident_id)
    data = v.body()
    v.reject_unknown(data, VOID_INPUT)
    v.as_string(data, "reason", required_field=False)

    _state_gate(
        incident["status"], ("REPORTED", "UNDER_REVIEW"),
        "Only a REPORTED or UNDER_REVIEW incident may be voided.",
    )
    incident["status"] = "VOIDED"
    db.bump_version(incident)
    services.resolve_linked_alerts(incident, released_by_resolution=True)
    return object_response(models.safety_incident_out(incident))


@bp.post("/student-rides/trip-alerts/<alert_id>/resolve")
@requires("SupportCenterAgent", "PlatformAdmin")
def resolve_alert(alert_id):
    alert = load_alert(alert_id)
    _state_gate(alert["status"], "OPEN", "Only an OPEN trip alert may be resolved.")
    alert["status"] = "RESOLVED"
    # A direct resolution call is NOT a sweep of the trip's open alerts.
    alert["released_by_resolution"] = False
    db.bump_version(alert)
    return object_response(models.trip_alert_out(alert))