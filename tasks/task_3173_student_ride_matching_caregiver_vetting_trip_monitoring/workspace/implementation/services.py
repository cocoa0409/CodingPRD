"""Shared domain operations: posture transitions, alert synthesis, incident
creation and the derived-count re-propagation that follows a trip mutation.

Transcribed from SCAFFOLD.yaml sections 1.2 (state machines) and 1.3
(calculations) with the prose in PRD sections 3.8 and 3.9.
"""

import calculations as calc
import db
from clock import fmt_dt, parse_dt, parse_date, stamp
from decimal import Decimal
from errors import ERR_NOT_FOUND, ApiError

ALERT_TRIP_DELAY = "TRIP_DELAY"
ALERT_GEOFENCE_BREACH = "GEOFENCE_BREACH"
ALERT_HANDOFF_DISPUTE = "HANDOFF_DISPUTE"
ALERT_STUDENT_ABSENT = "STUDENT_ABSENT"


# --- Derived-count re-propagation -------------------------------------------

def refresh_trip_relations(trip):
    """Re-propagate the counts a trip mutation touches (PRD section 3.11)."""
    district = db.get("districts", trip["district_id"])
    if district:
        calc.recompute_district(district)
    rider = db.get("riders", trip["rider_id"])
    if rider:
        calc.recompute_rider(rider)
    driver_id = trip.get("driver_id")
    if driver_id:
        driver = db.get("drivers", driver_id)
        if driver:
            calc.recompute_driver(driver)


def refresh_driver(driver):
    calc.recompute_driver(driver)
    return driver


# --- Trip posture (PRD 2.5) --------------------------------------------------

def apply_posture_discrepancy(trip):
    """Automatic NORMAL -> DISCREPANCY (never client-requested)."""
    if trip["safety_state"] == "NORMAL":
        trip["safety_state"] = "DISCREPANCY"
        db.bump_version(trip)
        return True
    return False


def apply_posture_locked(trip):
    """Automatic -> LOCKED (the HIGH-severity / suspension-cascade posture)."""
    if trip["safety_state"] != "LOCKED":
        trip["safety_state"] = "LOCKED"
        db.bump_version(trip)
        return True
    return False


def apply_grade_posture(trip, grade):
    """The absence grade sets the posture: LOW stays NORMAL."""
    if grade == "MEDIUM":
        return apply_posture_discrepancy(trip)
    if grade == "HIGH":
        return apply_posture_locked(trip)
    return False


# --- Trip alert synthesis (PRD 3.9) -----------------------------------------

def _severity_rank(severity):
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(severity, 0)


def create_trip_alert(trip, alert_type, source_incident_id=None,
                      released_by_resolution=False, severity_override=None):
    """Synthesise a TripAlert and derive its severity, routing and posture.

    Implements the whole alert-creation rule including:
      - the coordination rule (no second unresolved HIGH)
      - the continuous-monitoring cycle (a RESOLVED alert on a non-finished trip
        returns to OPEN when a new alert is synthesised, and the older alert's
        severity is raised to match the new one)
      - the automatic posture transition the new alert's severity implies

    ``severity_override`` pins the alert's severity when another published rule
    already fixed it. PRD §3.8 derives a reported absence's alert from the grade
    itself — "The grade sets the trip's postures and its consequences together.
    A `LOW` grade leaves the safety posture `NORMAL`; a `MEDIUM` grade moves it
    to `DISCREPANCY`; a `HIGH` grade moves it to `LOCKED`" — so a LOW-graded
    absence must not be re-escalated to the base `STUDENT_ABSENT` severity and
    lock a trip the grade left `NORMAL`.
    """
    district = db.get("districts", trip["district_id"])
    driver = db.get("drivers", trip["driver_id"]) if trip.get("driver_id") else None

    alert = db.new_record({
        "trip_id": trip["id"],
        "source_incident_id": source_incident_id,
        "alert_type": alert_type,
        "severity": "LOW",
        "notify_caregiver": False,
        "notify_school": False,
        "notify_support_center": False,
        "status": "OPEN",
        "released_by_resolution": released_by_resolution,
    })
    severity, caregiver, school, support = calc.trip_alert_severity(alert, trip, district, driver)
    if severity_override is not None:
        severity = severity_override
        caregiver = severity in ("MEDIUM", "HIGH")
        school = alert_type in ("HANDOFF_DISPUTE", "STUDENT_ABSENT") or severity == "HIGH"
        strikes = int((driver or {}).get("incident_strike_count") or 0)
        enabled = bool((district or {}).get("support_center_alert_enabled", True))
        support = (
            (severity == "HIGH" and (enabled or strikes >= calc.STRIKE_HIGH_MIN))
            or (school and alert_type == "HANDOFF_DISPUTE")
        )
    alert["severity"] = severity
    alert["notify_caregiver"] = caregiver
    alert["notify_school"] = school
    alert["notify_support_center"] = support
    db.save("trip_alerts", alert)

    # Posture precedence: a HIGH severity locks, otherwise a MEDIUM raises a
    # discrepancy. Applying the automatic posture here keeps the trip's
    # safety_state and the alert's severity consistent.
    if severity == "MEDIUM":
        apply_posture_discrepancy(trip)
    elif severity == "HIGH":
        apply_posture_locked(trip)
    else:
        db.bump_version(trip)
    return alert


def resolve_linked_alerts(incident, released_by_resolution):
    """Close every alert anchored to an incident."""
    for alert in db.all_of("trip_alerts"):
        if alert.get("source_incident_id") == incident["id"] and alert["status"] == "OPEN":
            alert["status"] = "RESOLVED"
            alert["released_by_resolution"] = released_by_resolution
            db.bump_version(alert)


# --- Safety incident creation -------------------------------------------------

def create_safety_incident(trip, category, severity, reported_by_actor=None,
                           summary=None, status="REPORTED"):
    """Open a safety incident with the trip's assigned driver attached."""
    incident = db.new_record({
        "trip_id": trip["id"] if trip else None,
        "driver_id": trip.get("driver_id") if trip else None,
        "category": category,
        "severity": severity,
        "reported_by_actor": reported_by_actor,
        "summary": summary,
        "adjudication": None,
        "resolution_note": None,
        "student_impact_score": 0,
        "status": status,
    })
    driver = db.get("drivers", incident["driver_id"]) if incident["driver_id"] else None
    incident["student_impact_score"] = calc.safety_incident_impact_score(incident, driver)
    db.save("safety_incidents", incident)
    return incident


# --- Trip completion ---------------------------------------------------------

def finalize_trip_completion(trip):
    """Lock in billable_ride_units at completion (PRD 3.8)."""
    trip["billable_ride_units"] = calc.trip_billable_ride_units(trip)
    trip["completed_at"] = stamp()
    trip["trip_state"] = "COMPLETED"


def recompute_impact_scores_for_driver(driver_id):
    driver = db.get("drivers", driver_id) if driver_id else None
    for incident in db.all_of("safety_incidents"):
        if incident["driver_id"] == driver_id:
            incident["student_impact_score"] = calc.safety_incident_impact_score(incident, driver)


# --- Nested resource resolution (PRD section 2.11) ---------------------------

def require_district(district_id):
    district = db.get("districts", district_id)
    if district is None:
        raise ApiError(ERR_NOT_FOUND, "The addressed district does not exist.")
    return district


def fmt_or_none(value):
    """Render a datetime the way the PRD prescribes, passing None through."""
    if value is None:
        return None
    return fmt_dt(value)


def num_or_none(value):
    """Echo a stored number without a Decimal leaking into the JSON encoder."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


# --- Trip window geometry (PRD section 2.6) ---------------------------------

def trip_window_instant(value):
    """Accept either a stored ISO string or an already-parsed datetime."""
    if value is None:
        return None
    from datetime import datetime

    if isinstance(value, datetime):
        return value
    return parse_dt(value)


def rider_window_collision(rider_id, dates):
    """Closed-interval test against the rider's existing non-terminal windows.

    PRD section 2.6: for a rider a window that merely touches another window is a
    collision, so the intervals are closed on both ends.
    """
    for trip in db.all_of("trips"):
        if trip["rider_id"] != rider_id:
            continue
        if trip["trip_state"] in ("COMPLETED", "CANCELLED"):
            continue
        existing_start = trip_window_instant(trip["window_start_at"])
        existing_end = trip_window_instant(trip["window_end_at"])
        for (start, end) in dates:
            if calc.closed_overlap(start, end, existing_start, existing_end):
                return trip
    return None


def driver_series_overlap(rr, dates_with_windows, driver):
    """Half-open driver-occupancy test used by series scheduling.

    PRD section 2.6 / 3.5: a generated series window that overlaps an interval
    already occupied by that driver is refused, with zero-minute gaps allowed.
    """
    for (start, end) in dates_with_windows:
        for trip in db.all_of("trips"):
            if trip.get("driver_id") != driver["id"]:
                continue
            if trip["trip_state"] in ("COMPLETED", "CANCELLED"):
                continue
            existing_start = trip_window_instant(trip["window_start_at"])
            existing_end = trip_window_instant(trip["window_end_at"])
            if calc.half_open_overlap(start, end, existing_start, existing_end):
                return trip
    return None


def build_trip_windows(rr, iso_dates):
    """Bind the request's time-of-day component to each generated date."""
    base_start = parse_dt(rr["window_start_at"])
    base_end = parse_dt(rr["window_end_at"])
    out = []
    for iso in iso_dates:
        d = parse_date(iso)
        start = base_start.replace(year=d.year, month=d.month, day=d.day)
        end = base_end.replace(year=d.year, month=d.month, day=d.day)
        out.append((iso, start, end))
    return out


# --- Trip creation -----------------------------------------------------------

def create_trip(rr, scheduled_date_iso, window_start_dt, window_end_dt,
                planned_miles=None, district_version_bump=True):
    """Instantiate a Trip against a RideRequest (PRD section 3.8)."""
    district = db.get("districts", rr["district_id"])
    contract = calc.covering_contract(rr["district_id"])
    period_key = None
    if contract:
        period_key = calc.billing_period_key(parse_date(scheduled_date_iso), contract["billing_period"])

    if planned_miles is None:
        planned_miles = rr.get("planned_miles", 0)

    trip = db.new_record({
        "district_id": rr["district_id"],
        "ride_request_id": rr["id"],
        "rider_id": rr["rider_id"],
        "driver_id": None,
        "scheduled_date": scheduled_date_iso,
        "window_start_at": fmt_dt(window_start_dt),
        "window_end_at": fmt_dt(window_end_dt),
        "window_start_at_dt": window_start_dt,
        "window_end_at_dt": window_end_dt,
        "pickup_address": rr["pickup_address"],
        "dropoff_address": rr["dropoff_address"],
        "trip_state": "SCHEDULED",
        "safety_state": "NORMAL",
        "candidate_driver_id": None,
        "claimed_by_user_id": None,
        "verified_by_user_id": None,
        "verified_authorized_adult_name": None,
        "billable_ride_units": 0,
        "planned_miles": planned_miles,
        "billable_miles": 0,
        "billing_period_key": period_key,
        "exception_code": None,
        "exception_recorded_at": None,
        "accepted_at": None,
        "completed_at": None,
        "arrived_at": None,
    })
    db.save("trips", trip)
    if district:
        calc.recompute_district(district)
        if district_version_bump:
            db.bump_version(district)
    return trip