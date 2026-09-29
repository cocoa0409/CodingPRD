"""Airframes and remote-ID broadcast modules (PRD 3.3)."""

from flask import Blueprint

import cascades
from auth import authenticate, check_body_owner, check_owns
from clockmod import clock
from common import collection_response, find, must_exist, string_filters
from envelope import ok
from errors import ApiError
from shape import bad, opt_str, raw_body, req_dt, req_enum, req_int, req_str, soft_body
from store import store, touch
from views import view

bp = Blueprint("aircraft", __name__)

PROTOCOLS = ("WIFI_NAN", "BLUETOOTH_LE")
REMOTE_ID_WEIGHT_THRESHOLD_G = 250


@bp.post("/aircraft")
def create_aircraft():
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_body_owner(caller, soft_body())
    body = raw_body()
    owner_pilot_id = req_str(body, "owner_pilot_id")
    model = req_str(body, "model", max_len=80)
    serial_number = req_str(body, "serial_number", max_len=40)
    takeoff_weight_g = req_int(body, "takeoff_weight_g", minimum=1, maximum=25000)
    max_altitude_ft = req_int(body, "max_altitude_ft", minimum=1, maximum=5000)
    owner = must_exist("pilots", owner_pilot_id)
    for other in store.all("aircraft"):
        if other["owner_pilot_id"] == owner["id"] \
                and other["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_AIRCRAFT_SERIAL")
    if owner["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    aircraft = store.insert("aircraft", {
        "owner_pilot_id": owner["id"],
        "model": model,
        "serial_number": serial_number,
        "takeoff_weight_g": takeoff_weight_g,
        "max_altitude_ft": max_altitude_ft,
        "remote_id_required": takeoff_weight_g > REMOTE_ID_WEIGHT_THRESHOLD_G,
        "registration_number": None,
        "registration_status": "PENDING_REGISTRATION",
        "grounding_reason": None,
    })
    return ok(view(aircraft), 201)


@bp.get("/aircraft/<aircraft_id>")
def read_aircraft(aircraft_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    check_owns(caller, find("aircraft", aircraft_id))
    aircraft = must_exist("aircraft", aircraft_id)
    return ok(view(aircraft))


@bp.get("/aircraft")
def list_aircraft():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority",
                           "InvestigationOfficer"))
    filters = string_filters("owner_pilot_id", "registration_status")
    return collection_response(caller, "aircraft", filters=filters)


@bp.post("/aircraft/<aircraft_id>/register")
def register_aircraft(aircraft_id):
    authenticate(("ComplianceOfficer",))
    aircraft = must_exist("aircraft", aircraft_id)
    if aircraft["registration_status"] != "PENDING_REGISTRATION":
        raise ApiError("ERR_AIRCRAFT_INVALID_STATE")
    owner = store.get("pilots", aircraft["owner_pilot_id"])
    if owner is not None and owner["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    cascades.check_remote_id(aircraft)
    aircraft["registration_status"] = "REGISTERED"
    aircraft["registration_number"] = store.next_registration_number()
    touch(aircraft)
    return ok(view(aircraft))


@bp.post("/aircraft/<aircraft_id>/ground")
def ground_aircraft_route(aircraft_id):
    authenticate(("ComplianceOfficer",))
    aircraft = must_exist("aircraft", aircraft_id)
    body = raw_body()
    reason = req_str(body, "grounding_reason", max_len=500)
    if aircraft["registration_status"] != "REGISTERED":
        raise ApiError("ERR_AIRCRAFT_INVALID_STATE")
    cascades.ground_aircraft(aircraft, reason)
    return ok(view(aircraft))


@bp.post("/aircraft/<aircraft_id>/return-to-service")
def return_aircraft_to_service(aircraft_id):
    authenticate(("ComplianceOfficer",))
    aircraft = must_exist("aircraft", aircraft_id)
    if aircraft["registration_status"] != "GROUNDED":
        raise ApiError("ERR_AIRCRAFT_INVALID_STATE")
    owner = store.get("pilots", aircraft["owner_pilot_id"])
    if owner is not None and owner["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_PILOT_SUSPENDED")
    cascades.check_remote_id(aircraft)
    aircraft["registration_status"] = "REGISTERED"
    aircraft["grounding_reason"] = None
    touch(aircraft)
    return ok(view(aircraft))


# ---------------------------------------------------------------------------
# remote-ID broadcast modules
# ---------------------------------------------------------------------------

@bp.post("/aircraft/<aircraft_id>/remote-id-modules")
def attach_module(aircraft_id):
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_owns(caller, find("aircraft", aircraft_id))
    aircraft = must_exist("aircraft", aircraft_id)
    body = raw_body()
    module_serial = req_str(body, "module_serial", max_len=40)
    protocol = req_enum(body, "broadcast_protocol", PROTOCOLS)
    firmware_version = req_str(body, "firmware_version", max_len=20)
    sample_ref = opt_str(body, "broadcast_sample_ref", max_len=200)
    for other in store.all("modules"):
        if other["aircraft_id"] == aircraft["id"] \
                and other["module_serial"] == module_serial:
            raise ApiError("ERR_DUPLICATE_MODULE_SERIAL")
    module = store.insert("modules", {
        "aircraft_id": aircraft["id"],
        "module_serial": module_serial,
        "broadcast_protocol": protocol,
        "firmware_version": firmware_version,
        "broadcast_sample_ref": sample_ref,
        "status": "UNVERIFIED",
        "verified_at": None,
        "verified_until": None,
        "failure_reason": None,
    })
    return ok(view(module), 201)


@bp.get("/remote-id-modules/<module_id>")
def read_module(module_id):
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    check_owns(caller, find("modules", module_id))
    module = must_exist("modules", module_id)
    return ok(view(module))


@bp.get("/remote-id-modules")
def list_modules():
    caller = authenticate(("Pilot", "ComplianceOfficer", "AirspaceAuthority"))
    filters = string_filters("aircraft_id", "status")
    return collection_response(caller, "modules", filters=filters)


@bp.post("/remote-id-modules/<module_id>/submit-verification")
def submit_module_verification(module_id):
    caller = authenticate(("Pilot", "ComplianceOfficer"))
    check_owns(caller, find("modules", module_id))
    module = must_exist("modules", module_id)
    body = raw_body()
    sample_ref = req_str(body, "broadcast_sample_ref", max_len=200)
    if module["status"] not in ("UNVERIFIED", "VERIFICATION_FAILED", "EXPIRED"):
        raise ApiError("ERR_MODULE_INVALID_STATE")
    module["broadcast_sample_ref"] = sample_ref
    module["failure_reason"] = None
    module["status"] = "VERIFICATION_PENDING"
    touch(module)
    return ok(view(module))


@bp.post("/remote-id-modules/<module_id>/verify")
def verify_module(module_id):
    authenticate(("ComplianceOfficer",))
    module = must_exist("modules", module_id)
    body = raw_body()
    outcome = req_enum(body, "outcome", ("VERIFIED", "FAILED"))
    verified_until = None
    failure_reason = None
    if outcome == "VERIFIED":
        verified_until = req_dt(body, "verified_until")
        if verified_until <= clock.now():
            raise bad("verified_until must be strictly after the current instant")
    else:
        failure_reason = req_str(body, "failure_reason", max_len=500)
    if module["status"] != "VERIFICATION_PENDING":
        raise ApiError("ERR_MODULE_INVALID_STATE")
    if outcome == "VERIFIED":
        module["status"] = "VERIFIED"
        module["verified_at"] = clock.now()
        module["verified_until"] = verified_until
        module["failure_reason"] = None
    else:
        module["status"] = "VERIFICATION_FAILED"
        module["failure_reason"] = failure_reason
        module["verified_at"] = None
        module["verified_until"] = None
    touch(module)
    return ok(view(module))
