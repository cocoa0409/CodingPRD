"""Entity serialisers.

Field names and types come from SCAFFOLD.yaml section 1.1 plus the common
field set in PRD section 2.7 (id, created_at, updated_at, version).

Timestamps are echoed back as stored (ISO 8601 UTC, three fractional digits).
Numbers declared as `type: number` are echoed as stored so the caller's own
precision is preserved.
"""

import middleware

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _common(record):
    return {key: record[key] for key in COMMON_FIELDS if key in record}


def district_out(d):
    out = {
        "name": d["name"],
        "billing_email": d["billing_email"],
        "contract_rate_per_ride_cents": d["contract_rate_per_ride_cents"],
        "contract_rate_per_mile_cents": d["contract_rate_per_mile_cents"],
        "minimum_billable_cents": d["minimum_billable_cents"],
        "no_school_dates": list(d.get("no_school_dates") or []),
        "bell_schedule_start": d.get("bell_schedule_start"),
        "support_center_alert_enabled": d.get("support_center_alert_enabled", True),
        "outstanding_balance_cents": d.get("outstanding_balance_cents", 0),
        "credit_balance_cents": d.get("credit_balance_cents", 0),
        "account_status": d.get("account_status", "ACTIVE"),
        "trips_scheduled_total": d.get("trips_scheduled_total", 0),
    }
    out.update(_common(d))
    return out


def rider_out(r, for_driver=False):
    phone = r.get("emergency_contact_phone")
    out = {
        "district_id": r["district_id"],
        "full_name": r["full_name"],
        "date_of_birth": r["date_of_birth"],
        "program_type": r["program_type"],
        "spi_level": r["spi_level"],
        "home_address": r["home_address"],
        "school_name": r["school_name"],
        "emergency_contact_phone": middleware.mask_phone(phone) if for_driver else phone,
        "authorized_adults": list(r.get("authorized_adults") or []),
        "notify_on_pickup": r["notify_on_pickup"],
        "notify_on_dropoff": r["notify_on_dropoff"],
        "support_center_phone_masked": r.get("support_center_phone_masked"),
        "active_ride_request_count": r.get("active_ride_request_count", 0),
        "status": r.get("status", "ACTIVE"),
    }
    out.update(_common(r))
    return out


def driver_out(d):
    out = {
        "full_name": d["full_name"],
        "phone": d["phone"],
        "employer_org": d["employer_org"],
        "caregiver_experience_months": d["caregiver_experience_months"],
        "language_codes": list(d.get("language_codes") or []),
        "vehicle_class": d["vehicle_class"],
        "seat_capacity": d["seat_capacity"],
        "child_seat_type": d.get("child_seat_type", "NONE"),
        "approved_seat_count": d.get("approved_seat_count", 0),
        "compliance_expires_at": d.get("compliance_expires_at"),
        "incident_strike_count": d.get("incident_strike_count", 0),
        "status": d.get("status", "PENDING"),
    }
    out.update(_common(d))
    return out


def background_check_out(c):
    out = {
        "driver_id": c["driver_id"],
        "check_type": c["check_type"],
        "reference_code": c["reference_code"],
        "result": c["result"],
        "expires_on": c["expires_on"],
        "cleared_after_months": c.get("cleared_after_months"),
    }
    out.update(_common(c))
    return out


def vehicle_inspection_out(i):
    out = {
        "driver_id": i["driver_id"],
        "vehicle_class": i["vehicle_class"],
        "seat_count": i["seat_count"],
        "child_seat_type": i.get("child_seat_type", "NONE"),
        "inspector_note": i.get("inspector_note"),
        "result": i["result"],
        "expires_on": i["expires_on"],
        "seat_credit": i.get("seat_credit", 0),
    }
    out.update(_common(i))
    return out


def contract_out(c):
    out = {
        "district_id": c["district_id"],
        "effective_from": c["effective_from"],
        "through_date": c["through_date"],
        "per_ride_rate_cents": c["per_ride_rate_cents"],
        "per_mile_rate_cents": c["per_mile_rate_cents"],
        "minimum_billable_cents": c["minimum_billable_cents"],
        "billing_period": c["billing_period"],
        "status": c.get("status", "DRAFT"),
    }
    out.update(_common(c))
    return out


def ride_request_out(rr):
    out = {
        "district_id": rr["district_id"],
        "rider_id": rr["rider_id"],
        "trip_type": rr["trip_type"],
        "required_specialty": rr.get("required_specialty", "NONE"),
        "window_start_at": rr["window_start_at"],
        "window_end_at": rr["window_end_at"],
        "max_window_minutes": rr.get("max_window_minutes", 30),
        "min_lead_time_hours": rr.get("min_lead_time_hours", 12),
        "pickup_address": rr["pickup_address"],
        "dropoff_address": rr["dropoff_address"],
        "planned_miles": rr.get("planned_miles", 0),
        "is_recurring": rr.get("is_recurring", False),
        "days_of_week": list(rr.get("days_of_week") or []),
        "series_effective_from": rr.get("series_effective_from"),
        "series_through_date": rr.get("series_through_date"),
        "series_no_school_dates": list(rr.get("series_no_school_dates") or []),
        "revision_count": rr.get("revision_count", 0),
        "status": rr.get("status", "DRAFT"),
        "recurring_series_active": rr.get("recurring_series_active", False),
    }
    out.update(_common(rr))
    return out


def trip_out(t):
    out = {
        "district_id": t["district_id"],
        "ride_request_id": t["ride_request_id"],
        "rider_id": t["rider_id"],
        "driver_id": t.get("driver_id"),
        "scheduled_date": t["scheduled_date"],
        "window_start_at": t["window_start_at"],
        "window_end_at": t["window_end_at"],
        "arrived_at": t.get("arrived_at"),
        "pickup_address": t["pickup_address"],
        "dropoff_address": t["dropoff_address"],
        "trip_state": t.get("trip_state", "SCHEDULED"),
        "safety_state": t.get("safety_state", "NORMAL"),
        "candidate_driver_id": t.get("candidate_driver_id"),
        "claimed_by_user_id": t.get("claimed_by_user_id"),
        "verified_by_user_id": t.get("verified_by_user_id"),
        "verified_authorized_adult_name": t.get("verified_authorized_adult_name"),
        "billable_ride_units": t.get("billable_ride_units", 0),
        "planned_miles": t.get("planned_miles", 0),
        "billable_miles": t.get("billable_miles", 0),
        "billing_period_key": t.get("billing_period_key"),
        "exception_code": t.get("exception_code"),
        "exception_recorded_at": t.get("exception_recorded_at"),
        "accepted_at": t.get("accepted_at"),
        "completed_at": t.get("completed_at"),
    }
    out.update(_common(t))
    return out


def handoff_out(h):
    out = {
        "trip_id": h["trip_id"],
        "leg": h["leg"],
        "expected_party": h["expected_party"],
        "verified_party_name": h["verified_party_name"],
        "verification_method": h["verification_method"],
        "authorized": h.get("authorized", False),
        "result": h.get("result", "FAILED"),
        "captured_at": h.get("captured_at"),
    }
    out.update(_common(h))
    return out


def safety_incident_out(inc):
    out = {
        "trip_id": inc.get("trip_id"),
        "driver_id": inc.get("driver_id"),
        "category": inc["category"],
        "severity": inc["severity"],
        "reported_by_actor": inc.get("reported_by_actor"),
        "summary": inc.get("summary"),
        "adjudication": inc.get("adjudication"),
        "resolution_note": inc.get("resolution_note"),
        "student_impact_score": inc.get("student_impact_score", 0),
        "status": inc.get("status", "REPORTED"),
    }
    out.update(_common(inc))
    return out


def trip_alert_out(a):
    out = {
        "trip_id": a["trip_id"],
        "source_incident_id": a.get("source_incident_id"),
        "alert_type": a["alert_type"],
        "severity": a.get("severity", "LOW"),
        "notify_caregiver": a.get("notify_caregiver", False),
        "notify_school": a.get("notify_school", False),
        "notify_support_center": a.get("notify_support_center", False),
        "status": a.get("status", "OPEN"),
        "released_by_resolution": a.get("released_by_resolution", False),
    }
    out.update(_common(a))
    return out


def geofence_out(g):
    out = {
        "district_id": g["district_id"],
        "label": g["label"],
        "center_lat": g["center_lat"],
        "center_lon": g["center_lon"],
        "radius_miles": g["radius_miles"],
        "registered_on": g.get("registered_on"),
    }
    out.update(_common(g))
    return out


def geofence_check_out(gc):
    out = {
        "trip_id": gc["trip_id"],
        "geofence_id": gc["geofence_id"],
        "observed_at": gc["observed_at"],
        "observed_lat": gc["observed_lat"],
        "observed_lon": gc["observed_lon"],
        "inside": gc.get("inside", False),
        "breach_alert_id": gc.get("breach_alert_id"),
    }
    out.update(_common(gc))
    return out


def billing_statement_out(s):
    out = {
        "district_id": s["district_id"],
        "contract_id": s.get("contract_id"),
        "period_key": s["period_key"],
        "period_start": s["period_start"],
        "period_end": s["period_end"],
        "total_ride_units": s.get("total_ride_units", 0),
        "total_miles": s.get("total_miles", 0),
        "total_amount_cents": s.get("total_amount_cents", 0),
        "applied_credit_cents": s.get("applied_credit_cents", 0),
        "issued_at": s.get("issued_at"),
        "status": s.get("status", "OPEN"),
    }
    out.update(_common(s))
    return out


SERIALISERS = {
    "districts": district_out,
    "riders": rider_out,
    "drivers": driver_out,
    "background_checks": background_check_out,
    "vehicle_inspections": vehicle_inspection_out,
    "contracts": contract_out,
    "ride_requests": ride_request_out,
    "trips": trip_out,
    "handoffs": handoff_out,
    "safety_incidents": safety_incident_out,
    "trip_alerts": trip_alert_out,
    "geofences": geofence_out,
    "geofence_checks": geofence_check_out,
    "billing_statements": billing_statement_out,
}


def serialise(coll_name, record):
    return SERIALISERS[coll_name](record)


def serialise_all(coll_name, records):
    return [SERIALISERS[coll_name](r) for r in records]


def rider_for_actor(rider, role):
    """Drivers only ever see the masked contact digest (PRD 3.2)."""
    return rider_out(rider, for_driver=(role == "Driver"))