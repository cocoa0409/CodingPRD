"""Instrument endpoints: registration, listing, lifecycle events, software
update application."""

from flask import Blueprint, request

from auth import require_action_role, require_ownership, require_roles
from cascades import decommission_instrument
from envelope import ok, ok_list, sort_items
from errors import ApiError, invalid_state, not_found
from serializers import instrument_json
from store import DB, new_id, now, stamp_new, touch
from validate import f_dt, f_enum, f_str, get_body, resolve_ref

bp = Blueprint("instruments", __name__)

EVENT_ACTIONS = {
    "SHIP": "FieldServiceEngineer",
    "INSTALL": "FieldServiceEngineer",
    "COMMISSION": "FieldServiceEngineer",
    "SERVICE_OPEN": "FieldServiceEngineer",
    "SERVICE_CLOSE": "FieldServiceEngineer",
    "DECOMMISSION": "AccountManager",
}


@bp.post("/genomics/instruments")
def create_instrument():
    require_roles("AccountManager")
    body = get_body()
    # Body references resolve (404) before shape validation per PRD 2.9 tier 6.
    resolve_ref(body, "model_id", "models")
    account_id = f_str(body, "account_id")
    model_id = f_str(body, "model_id")
    serial_number = f_str(body, "serial_number")
    regulatory_mode = f_enum(body, "regulatory_mode", ["RUO", "CLINICAL"])
    installed_at = f_dt(body, "installed_at", required=False)
    model = DB["models"][model_id]
    # Regulatory duality gate (priority 16).
    account = DB["accounts"].get(account_id)
    if (
        account is not None
        and account["regulatory_class"] == "CLINICAL"
        and regulatory_mode != "CLINICAL"
    ):
        raise ApiError(
            "ERR_REGULATORY_MODE_MISMATCH",
            422,
            "A CLINICAL account may only register CLINICAL instruments",
        )
    # Serial uniqueness (priority 21).
    if any(i["serial_number"] == serial_number for i in DB["instruments"].values()):
        raise ApiError("ERR_DUPLICATE_SERIAL", 409, "serial_number already registered")
    # Model support gate (priority 22).
    if model["support_status"] == "OBSOLETE":
        raise ApiError("ERR_MODEL_OBSOLETE", 422, "Model is OBSOLETE")
    instrument = {
        "id": new_id(),
        "account_id": account_id,
        "model_id": model_id,
        "serial_number": serial_number,
        "regulatory_mode": regulatory_mode,
        "installed_at": installed_at,
        "install_state": "ORDERED",
        "software_version": "1.0.0",
        "applied_update_ids": [],
        # Base modes unioned with unlocks of applied updates; applied updates
        # keep their modes even if later withdrawn (PRD 3.1: no retroactive lock).
        "unlocked_run_modes": list(model["base_run_modes"]),
        "service_windows": [],
        "decommissioned_at": None,
    }
    stamp_new(instrument)
    DB["instruments"][instrument["id"]] = instrument
    return ok(instrument_json(instrument), 201)


@bp.get("/genomics/instruments/<instrument_id>")
def get_instrument(instrument_id):
    uid, role = require_roles("AccountManager", "FieldServiceEngineer", "FinanceAdmin", "LabOperator")
    instrument = DB["instruments"].get(instrument_id)
    if instrument is None:
        raise not_found("Instrument not found")
    if role == "LabOperator":
        require_ownership(instrument["account_id"] == uid)
    return ok(instrument_json(instrument))


@bp.get("/genomics/instruments")
def list_instruments():
    require_roles("AccountManager", "FieldServiceEngineer", "SupplyPlanner", "FinanceAdmin")
    items = list(DB["instruments"].values())
    account_id = request.args.get("account_id")
    model_id = request.args.get("model_id")
    install_state = request.args.get("install_state")
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    if model_id is not None:
        items = [i for i in items if i["model_id"] == model_id]
    if install_state is not None:
        items = [i for i in items if i["install_state"] == install_state]
    return ok_list([instrument_json(i) for i in sort_items(items)])


@bp.post("/genomics/instruments/<instrument_id>/events")
def instrument_event(instrument_id):
    uid, role = require_roles("FieldServiceEngineer", "AccountManager")
    body = get_body()
    action = body.get("action")
    require_action_role(role, action, EVENT_ACTIONS)
    instrument = DB["instruments"].get(instrument_id)
    if instrument is None:
        raise not_found("Instrument not found")
    action = f_enum(body, "action", list(EVENT_ACTIONS.keys()))
    state = instrument["install_state"]
    t = now()
    if action == "SHIP":
        if state != "ORDERED":
            raise invalid_state("SHIP requires install_state ORDERED")
        instrument["install_state"] = "SHIPPED"
    elif action == "INSTALL":
        if state != "SHIPPED":
            raise invalid_state("INSTALL requires install_state SHIPPED")
        instrument["install_state"] = "INSTALLED"
        if instrument["installed_at"] is None:
            instrument["installed_at"] = t
    elif action == "COMMISSION":
        if state != "INSTALLED":
            raise invalid_state("COMMISSION requires install_state INSTALLED")
        instrument["install_state"] = "OPERATIONAL"
    elif action == "SERVICE_OPEN":
        if state != "OPERATIONAL":
            raise invalid_state("SERVICE_OPEN requires install_state OPERATIONAL")
        instrument["install_state"] = "DOWN_FOR_SERVICE"
        instrument["service_windows"].append({"opened_at": t, "closed_at": None})
    elif action == "SERVICE_CLOSE":
        if state != "DOWN_FOR_SERVICE":
            raise invalid_state("SERVICE_CLOSE requires install_state DOWN_FOR_SERVICE")
        open_windows = [w for w in instrument["service_windows"] if w["closed_at"] is None]
        if not open_windows:
            raise invalid_state("No open service window to close")
        open_windows[-1]["closed_at"] = t
        instrument["install_state"] = "OPERATIONAL"
    else:  # DECOMMISSION
        if state not in ("OPERATIONAL", "DOWN_FOR_SERVICE"):
            raise invalid_state("DECOMMISSION requires OPERATIONAL or DOWN_FOR_SERVICE")
        decommission_instrument(instrument)  # touches the instrument itself
        return ok(instrument_json(instrument))
    touch(instrument)
    return ok(instrument_json(instrument))


@bp.post("/genomics/instruments/<instrument_id>/software-updates")
def apply_update(instrument_id):
    require_roles("FieldServiceEngineer")
    instrument = DB["instruments"].get(instrument_id)
    if instrument is None:
        raise not_found("Instrument not found")
    body = get_body()
    resolve_ref(body, "update_id", "updates")
    update_id = f_str(body, "update_id")
    update = DB["updates"][update_id]
    # Gates in scaffold priority order (10, 11-extended, 13, 17, 24).
    has_active_contract = any(
        c["instrument_id"] == instrument_id and c["contract_state"] == "ACTIVE"
        for c in DB["contracts"].values()
    )
    if not has_active_contract:
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", 409, "An ACTIVE service contract must cover the instrument"
        )
    if instrument["install_state"] != "OPERATIONAL":
        raise ApiError(
            "ERR_INSTRUMENT_NOT_OPERATIONAL", 409, "Instrument must be OPERATIONAL"
        )
    if update["release_state"] != "RELEASED":
        raise ApiError("ERR_UPDATE_WITHDRAWN", 409, "Update has been withdrawn")
    if (
        instrument["regulatory_mode"] == "CLINICAL"
        and update["clinical_validation_status"] != "VALIDATED"
    ):
        raise ApiError(
            "ERR_UPDATE_NOT_VALIDATED_CLINICAL",
            422,
            "CLINICAL instruments require a VALIDATED update",
        )
    model = DB["models"][instrument["model_id"]]
    if update["min_model_generation"] > model["generation"]:
        raise ApiError(
            "ERR_UPDATE_MODEL_INCOMPATIBLE",
            422,
            "Update min_model_generation exceeds the instrument model generation",
        )
    instrument["software_version"] = update["update_version"]
    instrument["applied_update_ids"].append(update["id"])
    modes = list(model["base_run_modes"])
    for applied_id in instrument["applied_update_ids"]:
        applied = DB["updates"].get(applied_id)
        if applied is None:
            continue
        for mode in applied["unlocks_run_modes"]:
            if mode not in modes:
                modes.append(mode)
    instrument["unlocked_run_modes"] = modes
    touch(instrument)
    return ok(instrument_json(instrument))
