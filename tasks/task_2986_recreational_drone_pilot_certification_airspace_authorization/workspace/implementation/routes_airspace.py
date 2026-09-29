"""Zones, temporary flight restrictions and airspace authorizations (PRD 3.4)."""

from flask import Blueprint

import calc
import cascades
from auth import authenticate, check_body_owner, check_owns
from clockmod import clock
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import (opt_bool, opt_int, opt_str, raw_body, req_bool, req_dt, req_enum,
                   req_int, req_str, soft_body)
from store import store, touch
from views import view

bp = Blueprint("airspace", __name__)

CLASS_CODES = ("B", "C", "D", "E", "G")


# ---------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------

@bp.post("/airspace-zones")
def create_zone():
    authenticate(("AirspaceAuthority",))
    body = raw_body()
    designator = req_str(body, "designator", max_len=30)
    class_code = req_enum(body, "class_code", CLASS_CODES)
    class_ceiling_ft = req_int(body, "class_ceiling_ft", minimum=100, maximum=2000)
    requires_authorization = req_bool(body, "requires_authorization")
    max_concurrent = req_int(body, "max_concurrent_authorizations", minimum=1, maximum=20)
    relief = opt_bool(body, "structure_relief_eligible", default=False)
    for other in store.all("zones"):
        if other["designator"] == designator:
            raise ApiError("ERR_DUPLICATE_ZONE_DESIGNATOR")
    zone = store.insert("zones", {
        "designator": designator,
        "class_code": class_code,
        "class_ceiling_ft": class_ceiling_ft,
        "requires_authorization": requires_authorization,
        "max_concurrent_authorizations": max_concurrent,
        "structure_relief_eligible": relief,
        "reserved_slot_count": 0,
    })
    return ok(view(zone), 201)


@bp.get("/airspace-zones/<zone_id>")
def read_zone(zone_id):
    authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                  "InvestigationOfficer"))
    zone = must_exist("zones", zone_id)
    return ok(view(zone))


@bp.get("/airspace-zones")
def list_zones():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    return collection_response(caller, "zones", filters=string_filters("class_code"))


# ---------------------------------------------------------------------------
# temporary flight restrictions
# ---------------------------------------------------------------------------

@bp.post("/tfrs")
def create_tfr():
    caller = authenticate(("AirspaceAuthority",))
    body = raw_body()
    zone_id = req_str(body, "zone_id")
    reason = req_str(body, "reason", max_len=200)
    effective_from = req_dt(body, "effective_from")
    effective_until = req_dt(body, "effective_until")
    max_permitted = opt_int(body, "max_permitted_altitude_ft", minimum=0, maximum=2000)
    if effective_until <= effective_from:
        raise ApiError("ERR_INVALID_WINDOW",
                       "effective_until must be strictly after effective_from")
    zone = must_exist("zones", zone_id)
    tfr = store.insert("tfrs", {
        "zone_id": zone["id"],
        "reason": reason,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "max_permitted_altitude_ft": max_permitted,
        "status": "ACTIVE",
        "published_by_user_id": caller.user_id,
    })
    return ok(view(tfr), 201)


@bp.get("/tfrs/<tfr_id>")
def read_tfr(tfr_id):
    authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    tfr = must_exist("tfrs", tfr_id)
    return ok(view(tfr))


@bp.get("/tfrs")
def list_tfrs():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    filters = string_filters("zone_id", "status")
    return collection_response(caller, "tfrs", filters=filters)


@bp.post("/tfrs/<tfr_id>/lift")
def lift_tfr(tfr_id):
    authenticate(("AirspaceAuthority",))
    tfr = must_exist("tfrs", tfr_id)
    if tfr["status"] != "ACTIVE":
        raise ApiError("ERR_TFR_INVALID_STATE")
    tfr["status"] = "LIFTED"
    touch(tfr)
    return ok(view(tfr))


# ---------------------------------------------------------------------------
# airspace authorizations
# ---------------------------------------------------------------------------

@bp.post("/airspace-authorizations")
def create_authorization():
    caller = authenticate(("Pilot",))
    check_body_owner(caller, soft_body())
    body = raw_body()
    pilot_id = req_str(body, "pilot_id")
    aircraft_id = req_str(body, "aircraft_id")
    zone_id = req_str(body, "zone_id")
    waiver_id = opt_str(body, "waiver_id")
    requested_ceiling_ft = req_int(body, "requested_ceiling_ft", minimum=1, maximum=2000)
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    expected_zone_version = req_int(body, "expected_zone_version")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end must be strictly after window_start")
    pilot = must_exist("pilots", pilot_id)
    aircraft = must_exist("aircraft", aircraft_id)
    zone = must_exist("zones", zone_id)
    waiver = must_exist("waivers", waiver_id) if waiver_id is not None else None
    if aircraft["owner_pilot_id"] != pilot["id"]:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", "airframe belongs to another pilot")
    if zone["version"] != expected_zone_version:
        raise ApiError("ERR_STALE_ZONE_VERSION")
    if pilot["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    if pilot["status"] != "CERTIFIED":
        raise ApiError("ERR_PILOT_NOT_CERTIFIED")
    if calc.currency_lapsed(pilot):
        cascades.lapse_pilot_if_stale(pilot)
        raise ApiError("ERR_PILOT_CURRENCY_LAPSED")
    # Rung 18 names PENDING_REGISTRATION and DEREGISTERED only; a GROUNDED
    # airframe falls through to rung 19 (PRD 2.11).
    if aircraft["registration_status"] in ("PENDING_REGISTRATION", "DEREGISTERED"):
        raise ApiError("ERR_AIRCRAFT_NOT_REGISTERED")
    if aircraft["registration_status"] == "GROUNDED":
        raise ApiError("ERR_AIRCRAFT_GROUNDED")
    if requested_ceiling_ft > min(zone["class_ceiling_ft"], aircraft["max_altitude_ft"]):
        raise ApiError("ERR_ALTITUDE_CEILING_EXCEEDED")
    if pilot["operator_category"] == "COMMERCIAL":
        candidates = calc.covering_policy_candidates(pilot["id"], window_start,
                                                     window_end)
        if not candidates:
            raise ApiError("ERR_INSURANCE_NOT_ACTIVE")
        best = calc.select_covering_policy(candidates)
        if best["remaining_coverage_cents"] < calc.COMMERCIAL_MINIMUM_CENTS:
            raise ApiError("ERR_INSURANCE_COVERAGE_INSUFFICIENT")
    authorization = store.insert("authorizations", {
        "pilot_id": pilot["id"],
        "aircraft_id": aircraft["id"],
        "zone_id": zone["id"],
        "waiver_id": waiver["id"] if waiver else None,
        "requested_ceiling_ft": requested_ceiling_ft,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
        "granted_ceiling_ft": None,
        "approved_by_user_id": None,
        "decided_at": None,
        "denial_reason": None,
    })
    return ok(view(authorization), 201)


@bp.get("/airspace-authorizations/<authorization_id>")
def read_authorization(authorization_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    check_owns(caller, find("authorizations", authorization_id))
    authorization = must_exist("authorizations", authorization_id)
    return ok(view(authorization))


@bp.get("/airspace-authorizations")
def list_authorizations():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    filters = string_filters("pilot_id", "aircraft_id", "zone_id", "waiver_id", "status")
    return collection_response(caller, "authorizations", filters=filters)


@bp.post("/airspace-authorizations/<authorization_id>/decide")
def decide_authorization(authorization_id):
    caller = authenticate(("AirspaceAuthority",))
    authorization = must_exist("authorizations", authorization_id)
    body = raw_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    denial_reason = None
    if decision == "DENY":
        denial_reason = req_str(body, "denial_reason", max_len=500)
    if authorization["status"] != "REQUESTED":
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    pilot = store.get("pilots", authorization["pilot_id"])
    aircraft = store.get("aircraft", authorization["aircraft_id"])
    zone = store.get("zones", authorization["zone_id"])
    if decision == "DENY":
        authorization["status"] = "DENIED"
        authorization["denial_reason"] = denial_reason
        authorization["decided_at"] = clock.now()
        touch(authorization)
        return ok(view(authorization))
    if pilot["status"] != "CERTIFIED":
        raise ApiError("ERR_PILOT_NOT_CERTIFIED")
    if aircraft["registration_status"] != "REGISTERED":
        raise ApiError("ERR_AIRCRAFT_NOT_REGISTERED")
    if calc.overlapping_slot_count(zone["id"], authorization) \
            >= zone["max_concurrent_authorizations"]:
        raise ApiError("ERR_ZONE_CAPACITY_EXCEEDED")
    authorization["status"] = "APPROVED"
    authorization["granted_ceiling_ft"] = calc.granted_ceiling(authorization, pilot,
                                                               aircraft, zone)
    authorization["approved_by_user_id"] = caller.user_id
    authorization["decided_at"] = clock.now()
    touch(authorization)
    cascades.reserve_zone_slot(zone)
    return ok(view(authorization))


@bp.post("/airspace-authorizations/<authorization_id>/revoke")
def revoke_authorization_route(authorization_id):
    authenticate(("AirspaceAuthority",))
    authorization = must_exist("authorizations", authorization_id)
    body = raw_body()
    denial_reason = opt_str(body, "denial_reason", max_len=500)
    if authorization["status"] not in ("APPROVED", "ACTIVE"):
        raise ApiError("ERR_AUTHORIZATION_INVALID_STATE")
    cascades.revoke_authorization(authorization, denial_reason)
    return ok(view(authorization))
