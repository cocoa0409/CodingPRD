"""Resource serializers: strip internal fields, format timestamps.

Derived fields (Aircraft.posture / posture_reason, DocumentPermit.status) are
recomputed against the logical clock on every read per PRD 2.7.
"""

from services import aircraft_posture, document_status
from util import fmt_ts


def _common(r):
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "updated_at": fmt_ts(r["updated_at"]),
        "version": r["version"],
    }


def aircraft_json(a):
    out = _common(a)
    posture, reason = aircraft_posture(a)
    out.update({
        "tail_number": a["tail_number"],
        "aircraft_type": a["aircraft_type"],
        "passenger_capacity": a["passenger_capacity"],
        "home_base_icao": a["home_base_icao"],
        "status": a["status"],
        "posture": posture,
        "posture_reason": reason,
    })
    return out


def document_json(d):
    out = _common(d)
    out.update({
        "aircraft_id": d["aircraft_id"],
        "doc_kind": d["doc_kind"],
        "identifier": d["identifier"],
        "issued_at": fmt_ts(d["issued_at"]),
        "expires_at": fmt_ts(d["expires_at"]),
        "status": document_status(d),
    })
    return out


def crew_member_json(c):
    out = _common(c)
    out.update({
        "employee_number": c["employee_number"],
        "full_name": c["full_name"],
        "seat_qualification": c["seat_qualification"],
        "type_ratings": list(c["type_ratings"]),
        "training_valid_until": fmt_ts(c["training_valid_until"]),
        "duty_window_start_utc": fmt_ts(c["duty_window_start_utc"]),
        "duty_minutes_used": c["duty_minutes_used"],
        "status": c["status"],
    })
    return out


def business_unit_json(b):
    out = _common(b)
    out.update({
        "bu_code": b["bu_code"],
        "name": b["name"],
        "annual_flight_budget_cents": b["annual_flight_budget_cents"],
        "allocated_cents": b["allocated_cents"],
    })
    return out


def passenger_json(p):
    out = _common(p)
    out.update({
        "employee_number": p["employee_number"],
        "full_name": p["full_name"],
        "priority_tier": p["priority_tier"],
        "home_bu_id": p["home_bu_id"],
        "sifl_control_employee": p["sifl_control_employee"],
    })
    return out


def trip_json(t):
    out = _common(t)
    out.update({
        "requester_id": t["requester_id"],
        "charge_bu_id": t["charge_bu_id"],
        "trip_kind": t["trip_kind"],
        "purpose": t["purpose"],
        "requested_departure_utc": fmt_ts(t["requested_departure_utc"]),
        "requested_return_utc": fmt_ts(t["requested_return_utc"]),
        "passenger_ids": list(t["passenger_ids"]),
        "max_priority_tier": t["max_priority_tier"],
        "approval_status": t["approval_status"],
        "assignment_status": t["assignment_status"],
        "personal_use_flag": t["personal_use_flag"],
        "personal_use_approved_by": t["personal_use_approved_by"],
        "assigned_by_user_id": t["assigned_by_user_id"],
        "dispatched_by_user_id": t["dispatched_by_user_id"],
        "sifl_imputed_income_cents": t["sifl_imputed_income_cents"],
        "allocated_cost_cents": t["allocated_cost_cents"],
        "settlement_status": t["settlement_status"],
    })
    return out


def flight_leg_json(lg):
    out = _common(lg)
    out.update({
        "trip_request_id": lg["trip_request_id"],
        "leg_sequence": lg["leg_sequence"],
        "origin_icao": lg["origin_icao"],
        "destination_icao": lg["destination_icao"],
        "scheduled_departure_utc": fmt_ts(lg["scheduled_departure_utc"]),
        "scheduled_arrival_utc": fmt_ts(lg["scheduled_arrival_utc"]),
        "distance_statute_miles": lg["distance_statute_miles"],
        "aircraft_id": lg["aircraft_id"],
        "pic_crew_id": lg["pic_crew_id"],
        "sic_crew_id": lg["sic_crew_id"],
        "block_minutes": lg["block_minutes"],
        "status": lg["status"],
    })
    return out


def maintenance_window_json(w):
    out = _common(w)
    out.update({
        "aircraft_id": w["aircraft_id"],
        "window_start_utc": fmt_ts(w["window_start_utc"]),
        "window_end_utc": fmt_ts(w["window_end_utc"]),
        "maintenance_kind": w["maintenance_kind"],
        "status": w["status"],
    })
    return out


def catering_order_json(o):
    out = _common(o)
    out.update({
        "flight_leg_id": o["flight_leg_id"],
        "vendor_name": o["vendor_name"],
        "menu_code": o["menu_code"],
        "headcount": o["headcount"],
        "quoted_cost_cents": o["quoted_cost_cents"],
        "status": o["status"],
    })
    return out


def ground_transport_json(t):
    out = _common(t)
    out.update({
        "flight_leg_id": t["flight_leg_id"],
        "provider_name": t["provider_name"],
        "pickup_minutes_after_arrival": t["pickup_minutes_after_arrival"],
        "quoted_cost_cents": t["quoted_cost_cents"],
        "status": t["status"],
    })
    return out


def charter_supplement_json(c):
    out = _common(c)
    out.update({
        "trip_request_id": c["trip_request_id"],
        "vendor_name": c["vendor_name"],
        "quoted_cost_cents": c["quoted_cost_cents"],
        "aircraft_type_offered": c["aircraft_type_offered"],
        "status": c["status"],
    })
    return out


def sifl_rate_period_json(p):
    out = _common(p)
    out.update({
        "period_start_utc": fmt_ts(p["period_start_utc"]),
        "period_end_utc": fmt_ts(p["period_end_utc"]),
        "terminal_charge_cents": p["terminal_charge_cents"],
        "rate_band_1_cents_per_mile": p["rate_band_1_cents_per_mile"],
        "rate_band_2_cents_per_mile": p["rate_band_2_cents_per_mile"],
        "rate_band_3_cents_per_mile": p["rate_band_3_cents_per_mile"],
        "control_employee_multiplier_pct": p["control_employee_multiplier_pct"],
    })
    return out
