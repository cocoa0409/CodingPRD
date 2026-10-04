"""Vendor catalog: instrument models, reagent kits, software updates."""

from flask import Blueprint

from auth import require_roles
from calc import kit_capacity_gb
from envelope import ok
from errors import ApiError, not_found
from serializers import kit_json, model_json, update_json
from store import DB, new_id, stamp_new, touch
from validate import enum_list, f_enum, f_int, f_str, get_body

bp = Blueprint("catalog", __name__)

RUN_MODES = ["STD_SHORT", "STD_LONG", "HIGH_OUTPUT"]
CHEMISTRY_VERSIONS = ["V1", "V2", "V3"]
FLOW_CELL_VERSIONS = ["FC_LOW", "FC_MID", "FC_HIGH"]


def _duplicate(error_msg):
    return ApiError("ERR_INVALID_REQUEST", 409, error_msg)


@bp.post("/genomics/instrument-models")
def create_model():
    require_roles("PlatformAdmin")
    body = get_body()
    model_code = f_str(body, "model_code")
    generation = f_int(body, "generation", min_v=1)
    base_price_cents = f_int(body, "base_price_cents", min_v=0)
    supported = enum_list(body, "supported_chemistry_versions", CHEMISTRY_VERSIONS)
    base_run_modes = enum_list(body, "base_run_modes", RUN_MODES)
    support_status = f_enum(body, "support_status", ["CURRENT", "SUNSET", "OBSOLETE"], required=False)
    if support_status is None:
        support_status = "CURRENT"
    if any(m["model_code"] == model_code for m in DB["models"].values()):
        raise _duplicate("model_code must be unique")
    model = {
        "id": new_id(),
        "model_code": model_code,
        "generation": generation,
        "base_price_cents": base_price_cents,
        "supported_chemistry_versions": supported,
        "base_run_modes": base_run_modes,
        "support_status": support_status,
    }
    stamp_new(model)
    DB["models"][model["id"]] = model
    return ok(model_json(model), 201)


@bp.post("/genomics/reagent-kits")
def create_kit():
    require_roles("PlatformAdmin")
    body = get_body()
    kit_code = f_str(body, "kit_code")
    run_type = f_enum(body, "run_type", RUN_MODES)
    flow_cell_version = f_enum(body, "flow_cell_version", FLOW_CELL_VERSIONS)
    chemistry_version = f_enum(body, "chemistry_version", CHEMISTRY_VERSIONS)
    regulatory_clearance = f_enum(body, "regulatory_clearance", ["RUO_ONLY", "IVD"])
    shelf_life_days = f_int(body, "shelf_life_days", min_v=0)
    cold_chain_class = f_enum(body, "cold_chain_class", ["FROZEN_20", "REFRIGERATED_4"])
    price_cents = f_int(body, "price_cents", min_v=0)
    samples_per_kit = f_int(body, "samples_per_kit", min_v=0)
    min_model_generation = f_int(body, "min_model_generation", min_v=1)
    if any(k["kit_code"] == kit_code for k in DB["kits"].values()):
        raise _duplicate("kit_code must be unique")
    kit = {
        "id": new_id(),
        "kit_code": kit_code,
        "run_type": run_type,
        "flow_cell_version": flow_cell_version,
        "chemistry_version": chemistry_version,
        "regulatory_clearance": regulatory_clearance,
        "shelf_life_days": shelf_life_days,
        "cold_chain_class": cold_chain_class,
        "price_cents": price_cents,
        "samples_per_kit": samples_per_kit,
        "min_model_generation": min_model_generation,
        "capacity_gb": kit_capacity_gb(flow_cell_version, chemistry_version),
    }
    stamp_new(kit)
    DB["kits"][kit["id"]] = kit
    return ok(kit_json(kit), 201)


@bp.patch("/genomics/reagent-kits/<kit_id>")
def patch_kit(kit_id):
    require_roles("PlatformAdmin")
    kit = DB["kits"].get(kit_id)
    if kit is None:
        raise not_found("ReagentKit not found")
    body = get_body()
    price_cents = f_int(body, "price_cents", min_v=0)
    kit["price_cents"] = price_cents
    touch(kit)
    return ok(kit_json(kit))


@bp.post("/genomics/software-updates")
def create_update():
    require_roles("PlatformAdmin")
    body = get_body()
    update_version = f_str(body, "update_version")
    min_model_generation = f_int(body, "min_model_generation", min_v=1)
    unlocks_run_modes = enum_list(body, "unlocks_run_modes", RUN_MODES)
    clinical_validation_status = f_enum(
        body, "clinical_validation_status", ["VALIDATED", "NOT_VALIDATED"]
    )
    if any(u["update_version"] == update_version for u in DB["updates"].values()):
        raise _duplicate("update_version must be unique")
    update = {
        "id": new_id(),
        "update_version": update_version,
        "min_model_generation": min_model_generation,
        "unlocks_run_modes": unlocks_run_modes,
        "clinical_validation_status": clinical_validation_status,
        "release_state": "RELEASED",
    }
    stamp_new(update)
    DB["updates"][update["id"]] = update
    return ok(update_json(update), 201)


@bp.post("/genomics/software-updates/<update_id>/withdraw")
def withdraw_update(update_id):
    require_roles("PlatformAdmin")
    update = DB["updates"].get(update_id)
    if update is None:
        raise not_found("SoftwareUpdate not found")
    if update["release_state"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", 409, "Update is already withdrawn")
    update["release_state"] = "WITHDRAWN"
    touch(update)
    return ok(update_json(update))
