"""Network administration: care stations, TPAs, providers (PRD section 3.1)."""
from flask import Blueprint, request

import constants as C
import db
import response
import services
import validate as v
from errors import fail
from middleware import endpoint, require_owner

bp = Blueprint("network", __name__)


@bp.post("/community-care/care-stations")
@endpoint([C.ROLE_PLATFORM_ADMIN])
def create_care_station(user_id, role):
    b = v.body()
    name = v.req_str(b, "name")
    latitude = v.req_number(b, "latitude")
    longitude = v.req_number(b, "longitude")
    primary_wait_days = v.req_int(b, "primary_wait_days")
    specialty_wait_days = v.req_int(b, "specialty_wait_days")
    service_codes = v.req_str_list(b, "service_codes")
    if not (-90 <= latitude <= 90):
        fail("ERR_INVALID_REQUEST", "latitude must be within -90..90")
    if not (-180 <= longitude <= 180):
        fail("ERR_INVALID_REQUEST", "longitude must be within -180..180")
    if primary_wait_days < 0 or specialty_wait_days < 0:
        fail("ERR_INVALID_REQUEST", "wait days must be non-negative")
    rec = db.create("care_stations", {
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "primary_wait_days": primary_wait_days,
        "specialty_wait_days": specialty_wait_days,
        "service_codes": service_codes,
    })
    return response.ok(db.public(rec), code=201)


@bp.post("/community-care/tpas")
@endpoint([C.ROLE_PLATFORM_ADMIN])
def create_tpa(user_id, role):
    b = v.body()
    rec = db.create("tpas", {
        "name": v.req_str(b, "name"),
        "region_code": v.req_str(b, "region_code"),
        "contract_status": "ACTIVE",
        "adjudicated_events": 0,
        "denied_events": 0,
        "denial_rate": 0,
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/tpas/<rid>")
@endpoint(C.ALL_ROLES)
def get_tpa(user_id, role, rid):
    tpa = v.path_entity("tpas", rid, "TPA")
    return response.ok(db.public(tpa))


@bp.post("/community-care/tpas/<rid>/providers")
@endpoint([C.ROLE_TPA_ADMINISTRATOR])
def onboard_provider(user_id, role, rid):
    tpa = v.path_entity("tpas", rid, "TPA")
    b = v.body()
    name = v.req_str(b, "name")
    service_codes = v.req_str_list(b, "service_codes")
    contract_scheduling = v.req_enum(b, "contract_scheduling", C.CONTRACT_SCHEDULING)
    latitude = v.req_number(b, "latitude")
    longitude = v.req_number(b, "longitude")
    contract_rates = b.get("contract_rates")
    if contract_rates is None:
        contract_rates = {}
    if not isinstance(contract_rates, dict):
        fail("ERR_INVALID_REQUEST", "contract_rates must be an object")
    for key, val in contract_rates.items():
        if not isinstance(key, str) or not isinstance(val, int) or isinstance(val, bool):
            fail("ERR_INVALID_REQUEST",
                 "contract_rates must map service codes to integer cent rates")
    require_owner(user_id, tpa["id"], "TPA network")
    rec = db.create("providers", {
        "tpa_id": tpa["id"],
        "name": name,
        "service_codes": service_codes,
        "contract_rates": contract_rates,
        "contract_scheduling": contract_scheduling,
        "credentialing_status": "PENDING",
        "latitude": latitude,
        "longitude": longitude,
        "lifetime_paid_cents": 0,
        "current_paid_cents": 0,
        "reversed_cents": 0,
    })
    return response.ok(db.public(rec), code=201)


@bp.get("/community-care/tpas/<rid>/providers")
@endpoint(C.ALL_ROLES)
def list_providers(user_id, role, rid):
    v.path_entity("tpas", rid, "TPA")
    preds = []
    status = request.args.get("credentialing_status")
    if status is not None:
        preds.append(lambda p: p["credentialing_status"] == status)
    preds.append(lambda p: p["tpa_id"] == rid)
    return response.list_response("providers", preds)


# Legal credentialing transitions (PRD section 3.1): exactly these five pairs.
_CREDENTIAL_TRANSITIONS = {
    ("PENDING", "CREDENTIALED"),
    ("PENDING", "DECREDENTIALED"),
    ("CREDENTIALED", "SUSPENDED"),
    ("SUSPENDED", "CREDENTIALED"),
    ("CREDENTIALED", "DECREDENTIALED"),
}


@bp.post("/community-care/providers/<rid>/credential-decision")
@endpoint([C.ROLE_NETWORK_MANAGER])
def credential_decision(user_id, role, rid):
    provider = v.path_entity("providers", rid, "provider")
    b = v.body()
    target = v.req_enum(b, "target_status", C.CREDENTIAL_STATUSES)
    if (provider["credentialing_status"], target) not in _CREDENTIAL_TRANSITIONS:
        fail("ERR_INVALID_STATE",
             "no credentialing transition from %s to %s"
             % (provider["credentialing_status"], target))
    was_credentialed = provider["credentialing_status"] == "CREDENTIALED"
    provider["credentialing_status"] = target
    db.touch(provider)
    if was_credentialed and target == "DECREDENTIALED":
        services.decredential_cascade(provider)
    return response.ok(db.public(provider))
