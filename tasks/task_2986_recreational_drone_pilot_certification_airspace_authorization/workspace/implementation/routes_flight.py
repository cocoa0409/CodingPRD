"""Planning, clearing, flying and closing out a mission (PRD 3.7)."""

from flask import Blueprint

import calc
import cascades
from auth import authenticate, check_body_owner, check_owns
from clockmod import add_minutes, clock, fmt_dt
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import (bad, opt_bool, opt_str, raw_body, req_bool, req_dt, req_enum,
                   req_id_list, req_int, req_num, req_str, soft_body)
from store import store, touch
from views import view

bp = Blueprint("flight", __name__)

OPERATION_CATEGORIES = ("RECREATIONAL", "COMMERCIAL")
LIVE_FLIGHT_STATUSES = ("PLANNED", "PREFLIGHT_CLEARED", "IN_PROGRESS")
TURNAROUND_PAD_MINUTES = 30
FLAG_WAIVER_TYPES = (
    ("over_people", "OVER_PEOPLE"),
    ("night_operation", "NIGHT"),
    ("beyond_visual_line_of_sight", "BVLOS"),
)


def effective_ceiling(authorization_id):
    """The cited authorization's granted ceiling, else the bare 400-foot rule."""
    authorization = store.get("authorizations", authorization_id) \
        if authorization_id else None
    if authorization is not None and authorization.get("granted_ceiling_ft") is not None:
        return authorization["granted_ceiling_ft"]
    return calc.BASE_CEILING_FT


def overlapping_active_tfrs(zone_id, window_start, window_end):
    """ACTIVE restrictions on the zone whose half-open window overlaps, created_at ASC."""
    out = []
    for tfr in store.all("tfrs"):
        if tfr["zone_id"] != zone_id or tfr["status"] != "ACTIVE":
            continue
        if tfr["effective_from"] < window_end and tfr["effective_until"] > window_start:
            out.append(tfr)
    return out


def tfr_blocks(tfr, planned_max_altitude_ft):
    cap = tfr.get("max_permitted_altitude_ft")
    return cap is None or planned_max_altitude_ft > cap


def matching_waiver(waiver, pilot_id, aircraft_id, waiver_type, planned_end):
    if waiver is None:
        return False
    if waiver["waiver_type"] != waiver_type or waiver["status"] != "APPROVED":
        return False
    if waiver["pilot_id"] != pilot_id or waiver["aircraft_id"] != aircraft_id:
        return False
    if waiver.get("valid_until") is None or waiver["valid_until"] <= planned_end:
        return False
    return True


@bp.post("/flights")
def create_flight():
    caller = authenticate(("Pilot",))
    check_body_owner(caller, soft_body())
    body = raw_body()
    pilot_id = req_str(body, "pilot_id")
    aircraft_id = req_str(body, "aircraft_id")
    zone_id = req_str(body, "zone_id")
    authorization_id = opt_str(body, "authorization_id")
    waiver_id = opt_str(body, "waiver_id")
    operation_category = req_enum(body, "operation_category", OPERATION_CATEGORIES)
    planned_start = req_dt(body, "planned_start")
    planned_end = req_dt(body, "planned_end")
    planned_max_altitude_ft = req_int(body, "planned_max_altitude_ft", minimum=1,
                                      maximum=2000)
    launch_latitude = req_num(body, "launch_latitude", minimum=-90.0, maximum=90.0)
    launch_longitude = req_num(body, "launch_longitude", minimum=-180.0, maximum=180.0)
    flags = {}
    for key, _ in FLAG_WAIVER_TYPES:
        flags[key] = opt_bool(body, key, default=False)
    raised = [waiver_type for key, waiver_type in FLAG_WAIVER_TYPES if flags[key]]
    if len(raised) > 1:
        raise bad("only one special-operation flag may be raised on a single flight")
    # Rung 8
    if planned_end <= planned_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "planned_end must be strictly after planned_start")
    if planned_start < clock.now():
        raise ApiError("ERR_INVALID_WINDOW", "planned_start may not sit in the past")
    # Rung 9
    pilot = must_exist("pilots", pilot_id)
    aircraft = must_exist("aircraft", aircraft_id)
    zone = must_exist("zones", zone_id)
    authorization = must_exist("authorizations", authorization_id) \
        if authorization_id else None
    waiver = must_exist("waivers", waiver_id) if waiver_id else None
    if aircraft["owner_pilot_id"] != pilot["id"]:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "airframe belongs to another pilot")
    # Rung 15
    if pilot["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    # Rung 16
    if pilot["status"] != "CERTIFIED":
        raise ApiError("ERR_PILOT_NOT_CERTIFIED")
    # Rung 17: the recomputed currency must outlast both the clock and the plan.
    projected, _, _, _ = calc.currency_projection(pilot)
    if projected is None or projected <= clock.now():
        cascades.lapse_pilot_if_stale(pilot)
        raise ApiError("ERR_PILOT_CURRENCY_LAPSED")
    if projected <= planned_end:
        raise ApiError("ERR_PILOT_CURRENCY_LAPSED",
                       "currency expires before the planned window ends")
    # Rungs 18 and 19
    if aircraft["registration_status"] in ("PENDING_REGISTRATION", "DEREGISTERED"):
        raise ApiError("ERR_AIRCRAFT_NOT_REGISTERED")
    if aircraft["registration_status"] == "GROUNDED":
        raise ApiError("ERR_AIRCRAFT_GROUNDED")
    # Rung 23
    if raised:
        if not matching_waiver(waiver, pilot["id"], aircraft["id"], raised[0],
                               planned_end):
            raise ApiError("ERR_WAIVER_REQUIRED")
    # Rung 24
    if zone["requires_authorization"]:
        if authorization is None or authorization["status"] != "APPROVED" \
                or authorization["pilot_id"] != pilot["id"] \
                or authorization["aircraft_id"] != aircraft["id"] \
                or authorization["zone_id"] != zone["id"]:
            raise ApiError("ERR_AUTHORIZATION_REQUIRED")
    # Rung 25
    if authorization is not None:
        if planned_start < authorization["window_start"] \
                or planned_end >= authorization["window_end"]:
            raise ApiError("ERR_AUTHORIZATION_WINDOW_MISMATCH")
    # Rung 26
    ceiling = effective_ceiling(authorization_id)
    if planned_max_altitude_ft > ceiling:
        raise ApiError("ERR_ALTITUDE_CEILING_EXCEEDED")
    # Rung 27
    if operation_category == "COMMERCIAL" \
            and pilot["operator_category"] != "COMMERCIAL":
        raise ApiError("ERR_RECREATIONAL_OPERATION_FORBIDDEN",
                       "a recreational operator may fly only RECREATIONAL operations")
    # Rung 29: the one padded interval rule, inclusive on both ends.
    padded_start = add_minutes(planned_start, -TURNAROUND_PAD_MINUTES)
    padded_end = add_minutes(planned_end, TURNAROUND_PAD_MINUTES)
    for other in store.all("flights"):
        if other["aircraft_id"] != aircraft["id"]:
            continue
        if other["status"] not in LIVE_FLIGHT_STATUSES:
            continue
        if other["planned_start"] <= padded_end \
                and other["planned_end"] >= padded_start:
            raise ApiError("ERR_AIRCRAFT_SCHEDULE_CONFLICT")
    # Rungs 35, 36 and 37
    covering_policy_id = None
    if operation_category == "COMMERCIAL":
        cascades.expire_policies_of_pilot(pilot["id"])
        candidates = calc.covering_policy_candidates(pilot["id"], planned_start,
                                                     planned_end)
        if not candidates:
            raise ApiError("ERR_INSURANCE_NOT_ACTIVE")
        indemnified = [p for p in candidates
                       if p["indemnification_clause_accepted"]]
        if not indemnified:
            raise ApiError("ERR_INDEMNIFICATION_NOT_ACCEPTED")
        adequate = [p for p in indemnified
                    if p["remaining_coverage_cents"] >= calc.COMMERCIAL_MINIMUM_CENTS]
        if not adequate:
            raise ApiError("ERR_INSURANCE_COVERAGE_INSUFFICIENT")
        covering_policy_id = calc.select_covering_policy(adequate)["id"]
    flight = store.insert("flights", {
        "pilot_id": pilot["id"],
        "aircraft_id": aircraft["id"],
        "zone_id": zone["id"],
        "authorization_id": authorization["id"] if authorization else None,
        "waiver_id": waiver["id"] if waiver else None,
        "covering_policy_id": covering_policy_id,
        "operation_category": operation_category,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "planned_max_altitude_ft": planned_max_altitude_ft,
        "launch_latitude": launch_latitude,
        "launch_longitude": launch_longitude,
        "over_people": flags["over_people"],
        "night_operation": flags["night_operation"],
        "beyond_visual_line_of_sight": flags["beyond_visual_line_of_sight"],
        "status": "PLANNED",
        "investigation_status": "NONE",
        "actual_start": None,
        "actual_end": None,
        "max_altitude_reached_ft": None,
        "incident_occurred": None,
        "incident_summary": None,
        "altitude_exceedance": False,
        "logged_minutes": 0,
        "cancellation_reason": None,
    })
    return ok(view(flight), 201)


@bp.get("/flights/<flight_id>")
def read_flight(flight_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    return ok(view(flight))


@bp.get("/flights")
def list_flights():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    filters = string_filters("pilot_id", "aircraft_id", "zone_id", "authorization_id",
                             "waiver_id", "covering_policy_id", "status",
                             "investigation_status")
    return collection_response(caller, "flights", filters=filters)


# ---------------------------------------------------------------------------
# the pre-flight sweep
# ---------------------------------------------------------------------------

def run_lazy_transitions(flight):
    """The four transitions of PRD 2.8 that a read gate performs for itself.

    The pilot lapse is deliberately excluded here: rung 17 owns it so that a
    lapsed pilot yields ERR_PILOT_CURRENCY_LAPSED rather than being masked by
    the certification gate at rung 16. The module expiry does run here, so a
    launch that fails on some earlier rung still leaves the stale module row
    correctly transitioned; rungs 20 and 21 are written to survive that, since
    rung 20 counts an EXPIRED module as present and lets rung 21 own the verdict.
    """
    aircraft = store.get("aircraft", flight["aircraft_id"])
    if aircraft is not None:
        cascades.expire_modules_of_aircraft(aircraft)
    cascades.expire_authorization(store.get("authorizations",
                                            flight.get("authorization_id")))
    cascades.expire_tfrs_of_zone(store.get("zones", flight["zone_id"]))


@bp.post("/flights/<flight_id>/preflight-check")
def preflight_check(flight_id):
    caller = authenticate(("Pilot",))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    body = raw_body()
    acknowledged = req_id_list(body, "acknowledged_tfr_ids")
    if flight["status"] != "PLANNED":
        raise ApiError("ERR_FLIGHT_INVALID_STATE")
    # Lazy state discovery precedes every gate verdict (PRD 2.8).
    run_lazy_transitions(flight)
    pilot = store.get("pilots", flight["pilot_id"])
    cascades.lapse_pilot_if_stale(pilot)
    aircraft = store.get("aircraft", flight["aircraft_id"])
    zone = store.get("zones", flight["zone_id"])
    authorization = store.get("authorizations", flight.get("authorization_id"))
    waiver = store.get("waivers", flight.get("waiver_id"))
    active_tfrs = overlapping_active_tfrs(zone["id"], flight["planned_start"],
                                          flight["planned_end"])
    active_tfr_ids = [tfr["id"] for tfr in active_tfrs]
    findings = set()
    if aircraft["registration_status"] != "REGISTERED":
        findings.add("AIRCRAFT_NOT_REGISTERED")
    if zone["requires_authorization"] \
            and (authorization is None or authorization["status"] != "APPROVED"):
        findings.add("AUTHORIZATION_NOT_APPROVED")
    projected, _, _, _ = calc.currency_projection(pilot)
    if pilot["status"] != "CERTIFIED" or projected is None \
            or projected <= clock.now():
        findings.add("CURRENCY_LAPSED")
    if aircraft["remote_id_required"] \
            and cascades.active_verified_module(aircraft) is None:
        findings.add("REMOTE_ID_INVALID")
    for tfr in active_tfrs:
        if tfr_blocks(tfr, flight["planned_max_altitude_ft"]):
            findings.add("TFR_TOTAL_BAN")
            break
    for tfr_id in active_tfr_ids:
        if tfr_id not in acknowledged:
            findings.add("TFR_UNACKNOWLEDGED")
            break
    raised = [waiver_type for key, waiver_type in FLAG_WAIVER_TYPES if flight[key]]
    if raised and not matching_waiver(waiver, flight["pilot_id"], flight["aircraft_id"],
                                      raised[0], flight["planned_end"]):
        findings.add("WAIVER_MISSING")
    blocking_findings = sorted(findings)
    record = store.insert("preflight_checks", {
        "flight_id": flight["id"],
        "checked_at": clock.now(),
        "result": "PASSED" if not blocking_findings else "FAILED",
        "blocking_findings": blocking_findings,
        "active_tfr_ids": active_tfr_ids,
        "acknowledged_tfr_ids": acknowledged,
        "airspace_class_code": zone["class_code"],
        "effective_ceiling_ft": effective_ceiling(flight.get("authorization_id")),
    }, versioned=False)
    if not blocking_findings:
        # A PASSED check clears the flight and bumps its version; a FAILED check
        # is an advisory that deliberately leaves the flight untouched.
        flight["status"] = "PREFLIGHT_CLEARED"
        touch(flight)
    return ok(view(record), 201)


@bp.get("/flights/<flight_id>/preflight-checks")
def list_preflight_checks(flight_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    rows = [row for row in store.all("preflight_checks")
            if row["flight_id"] == flight["id"]]
    return collection_response(caller, "preflight_checks", rows=rows)


# ---------------------------------------------------------------------------
# launch, completion and cancellation
# ---------------------------------------------------------------------------

@bp.post("/flights/<flight_id>/launch")
def launch_flight(flight_id):
    caller = authenticate(("Pilot",))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    # Rung 13 with its single carve-out: PLANNED falls through to rung 14.
    if flight["status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        raise ApiError("ERR_FLIGHT_INVALID_STATE")
    if flight["status"] != "PREFLIGHT_CLEARED":
        raise ApiError("ERR_PREFLIGHT_NOT_CLEARED")
    run_lazy_transitions(flight)
    pilot = store.get("pilots", flight["pilot_id"])
    aircraft = store.get("aircraft", flight["aircraft_id"])
    zone = store.get("zones", flight["zone_id"])
    authorization = store.get("authorizations", flight.get("authorization_id"))
    # Rung 15
    if pilot["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    # Rung 16
    if pilot["status"] != "CERTIFIED":
        raise ApiError("ERR_PILOT_NOT_CERTIFIED")
    # Rung 17
    projected, _, _, _ = calc.currency_projection(pilot)
    if projected is None or projected <= clock.now():
        cascades.lapse_pilot_if_stale(pilot)
        raise ApiError("ERR_PILOT_CURRENCY_LAPSED")
    # Rungs 18 and 19
    if aircraft["registration_status"] in ("PENDING_REGISTRATION", "DEREGISTERED"):
        raise ApiError("ERR_AIRCRAFT_NOT_REGISTERED")
    if aircraft["registration_status"] == "GROUNDED":
        raise ApiError("ERR_AIRCRAFT_GROUNDED")
    # Rungs 20 and 21
    cascades.check_remote_id(aircraft)
    # Rung 22: a null cap is a total ban that acknowledgement cannot clear.
    for tfr in overlapping_active_tfrs(zone["id"], flight["planned_start"],
                                       flight["planned_end"]):
        if tfr_blocks(tfr, flight["planned_max_altitude_ft"]):
            raise ApiError("ERR_TFR_ACTIVE")
    # The cited authorization must be APPROVED and live at this instant.
    if authorization is not None:
        now = clock.now()
        if authorization["status"] != "APPROVED" \
                or authorization["window_start"] > now \
                or authorization["window_end"] <= now:
            raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    flight["status"] = "IN_PROGRESS"
    flight["actual_start"] = clock.now()
    touch(flight)
    if authorization is not None:
        # The slot is kept: APPROVED and ACTIVE both hold a zone slot.
        authorization["status"] = "ACTIVE"
        touch(authorization)
    return ok(view(flight))


@bp.post("/flights/<flight_id>/complete")
def complete_flight(flight_id):
    caller = authenticate(("Pilot",))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    body = raw_body()
    actual_end = req_dt(body, "actual_end")
    max_altitude_reached_ft = req_int(body, "max_altitude_reached_ft", minimum=0)
    incident_occurred = req_bool(body, "incident_occurred")
    if incident_occurred:
        incident_summary = req_str(body, "incident_summary", max_len=2000)
    else:
        incident_summary = opt_str(body, "incident_summary", max_len=2000)
    if flight["status"] != "IN_PROGRESS":
        raise ApiError("ERR_FLIGHT_INVALID_STATE")
    if actual_end <= flight["actual_start"]:
        raise ApiError("ERR_INVALID_WINDOW",
                       "actual_end must be strictly after actual_start")
    flight["actual_end"] = actual_end
    flight["max_altitude_reached_ft"] = max_altitude_reached_ft
    flight["incident_occurred"] = incident_occurred
    flight["incident_summary"] = incident_summary
    elapsed = actual_end - flight["actual_start"]
    flight["logged_minutes"] = int(elapsed.total_seconds() // 60)
    flight["altitude_exceedance"] = \
        max_altitude_reached_ft > effective_ceiling(flight.get("authorization_id"))
    flight["status"] = "COMPLETED"
    touch(flight)
    authorization = store.get("authorizations", flight.get("authorization_id"))
    if authorization is not None and authorization["status"] == "ACTIVE":
        authorization["status"] = "CONSUMED"
        touch(authorization)
        cascades.release_zone_slot(authorization)
    pilot = store.get("pilots", flight["pilot_id"])
    pilot["last_completed_flight_end"] = actual_end
    calc.write_currency(pilot)
    calc.recompute_risk_score(pilot)
    touch(pilot)
    cascades.maybe_auto_suspend(pilot)
    return ok(view(flight))


@bp.post("/flights/<flight_id>/cancel")
def cancel_flight(flight_id):
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_owns(caller, find("flights", flight_id))
    flight = must_exist("flights", flight_id)
    body = raw_body()
    reason = req_str(body, "cancellation_reason", max_len=500)
    if flight["status"] not in ("PLANNED", "PREFLIGHT_CLEARED"):
        raise ApiError("ERR_FLIGHT_INVALID_STATE")
    # Nothing is released on the zone: the slot belongs to the authorization.
    flight["status"] = "CANCELLED"
    flight["cancellation_reason"] = reason
    touch(flight)
    return ok(view(flight))
