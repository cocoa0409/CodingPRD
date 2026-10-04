"""FacilityContract endpoints plus nested RateSchedule creation."""

from flask import Blueprint

from calc import cap_for_facility
from core import (ALL_ROLES, DB, auth, body, err, list_response, new_entity,
                  ok_obj, opt_dt, pub, req_dt, req_enum, req_int, req_num,
                  req_str, touch, apply_filters)

bp = Blueprint("contracts", __name__)

COMMISSION_BASIS = ("GROSS", "NET")

RATE_FIELDS = (
    "local_per_minute_cents",
    "intrastate_per_minute_cents",
    "interstate_per_minute_cents",
    "international_per_minute_cents",
    "connection_fee_cents",
    "message_price_cents",
    "video_session_fee_cents",
)


def contract_or_404(contract_id):
    contract = DB.contracts.get(contract_id)
    if contract is None:
        err("ERR_CONTRACT_NOT_FOUND", 404,
            "FacilityContract %s does not exist" % contract_id)
    return contract


@bp.post("/comm-services/contracts")
def create_contract():
    auth(["PlatformAdmin"])
    data = body()
    commission_pct = req_num(data, "commission_pct")
    commission_basis = req_enum(data, "commission_basis", COMMISSION_BASIS)
    deposit_fee = req_int(data, "deposit_fee_cents")
    closure_fee = req_int(data, "closure_fee_cents")
    effective_from = req_dt(data, "effective_from")
    effective_to = opt_dt(data, "effective_to")
    facility_id = req_str(data, "facility_id")
    if facility_id not in DB.facilities:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    entity = new_entity()
    entity.update({
        "facility_id": facility_id,
        "commission_pct": commission_pct,
        "commission_basis": commission_basis,
        "deposit_fee_cents": deposit_fee,
        "closure_fee_cents": closure_fee,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
    })
    DB.contracts[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/contracts/<contract_id>")
def get_contract(contract_id):
    auth(ALL_ROLES)
    return ok_obj(pub(contract_or_404(contract_id)))


@bp.get("/comm-services/contracts")
def list_contracts():
    auth(ALL_ROLES)
    items = apply_filters(DB.contracts.values(), ["facility_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/contracts/<contract_id>/activate")
def activate_contract(contract_id):
    auth(["PlatformAdmin"])
    contract = contract_or_404(contract_id)
    if contract["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409,
            "Only a DRAFT contract can be activated")
    facility = DB.facilities.get(contract["facility_id"])
    if facility is None or facility["status"] not in ("ONBOARDING", "ACTIVE"):
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Contract activation requires the facility to be ONBOARDING or ACTIVE")
    cap = cap_for_facility(facility)
    if cap is None:
        err("ERR_CAP_NOT_CONFIGURED", 409,
            "No RegulatoryCap row exists for state_code %s"
            % facility["state_code"])
    if contract["commission_pct"] > cap["max_commission_pct"]:
        # A commission exactly equal to the cap is acceptable.
        err("ERR_COMMISSION_EXCEEDS_CAP", 409,
            "commission_pct exceeds the jurisdictional maximum")
    for other in DB.contracts.values():
        if (other["id"] != contract["id"]
                and other["facility_id"] == contract["facility_id"]
                and other["status"] == "ACTIVE"):
            err("ERR_ACTIVE_CONTRACT_EXISTS", 409,
                "Another contract for this facility is already ACTIVE")
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok_obj(pub(contract))


@bp.post("/comm-services/contracts/<contract_id>/terminate")
def terminate_contract(contract_id):
    auth(["PlatformAdmin"])
    contract = contract_or_404(contract_id)
    if contract["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409,
            "Only an ACTIVE contract can be terminated")
    contract["status"] = "TERMINATED"
    touch(contract)
    # The contract's ACTIVE RateSchedule, if any, is superseded in the same
    # motion; CallRecords keep their pinned schedule and applied rates.
    for schedule in DB.schedules.values():
        if schedule["contract_id"] == contract["id"] and schedule["status"] == "ACTIVE":
            schedule["status"] = "SUPERSEDED"
            touch(schedule)
    return ok_obj(pub(contract))


@bp.post("/comm-services/contracts/<contract_id>/rate-schedules")
def create_rate_schedule(contract_id):
    auth(["PlatformAdmin"])
    data = body()
    rates = {name: req_int(data, name) for name in RATE_FIELDS}
    contract = contract_or_404(contract_id)
    if contract["status"] == "TERMINATED":
        err("ERR_INVALID_STATE", 409,
            "A rate schedule cannot be added to a TERMINATED contract")
    entity = new_entity()
    entity.update({
        "contract_id": contract_id,
        "status": "DRAFT",
        "activated_at": None,
    })
    entity.update(rates)
    DB.schedules[entity["id"]] = entity
    return ok_obj(pub(entity), 201)
