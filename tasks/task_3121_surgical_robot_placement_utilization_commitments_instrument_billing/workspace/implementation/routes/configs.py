"""System configuration catalog and software releases."""

from flask import Blueprint

from db import DB, base_record, as_bool, as_int, as_list, as_str, touch
from errors import ApiError
from middleware import authenticate
from response import success
from routes import common
from serializers import (system_configuration as ser_config,
                         software_release as ser_release)
from services import calc

bp = Blueprint("configs", __name__)

MODEL_CODES = ("DA_V1", "DA_V2", "SP_V1", "SP_V2", "SP_V3")


@bp.post("/api/system-configurations")
def create_configuration():
    authenticate(["PlatformAdmin"])
    data = common.body()
    model_code = common.require_str(data, "model_code")
    if model_code not in MODEL_CODES:
        raise ApiError("ERR_INVALID_REQUEST")
    record = base_record({
        "model_code": model_code,
        "base_placement_fee_cents": as_int(data.get("base_placement_fee_cents"), 0),
        "max_instrument_lives": as_int(data.get("max_instrument_lives"), 0),
        "feature_entitlements": as_list(data.get("feature_entitlements")),
        "requires_dark_fiber": as_bool(data.get("requires_dark_fiber")),
        "requires_dedicated_power_circuit": as_bool(data.get("requires_dedicated_power_circuit")),
        "integration_tier": as_int(data.get("integration_tier"), 1),
        "min_operating_room_length_cm": as_int(data.get("min_operating_room_length_cm"), 0),
        "min_operating_room_width_cm": as_int(data.get("min_operating_room_width_cm"), 0),
        "min_table_throw_radius_cm": as_int(data.get("min_table_throw_radius_cm"), 0),
        "min_ceiling_clearance_cm": as_int(data.get("min_ceiling_clearance_cm"), 0),
        "status": "ACTIVE",
    })
    DB.system_configurations[record["id"]] = record
    return success(ser_config(record)), 201


@bp.get("/api/system-configurations")
def list_configurations():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead"])
    records = list(DB.system_configurations.values())
    status = common.arg("status")
    if status:
        records = [r for r in records if r.get("status") == status]
    return common.paged(records, "system_configurations")


@bp.get("/api/system-configurations/<config_id>")
def get_configuration(config_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ClinicalOperationsLead"])
    return success(ser_config(common.get_config(config_id)))


@bp.put("/api/system-configurations/<config_id>")
def update_configuration(config_id):
    """Update a configuration's commercial or dimensional attributes.

    Retiring a configuration is not inert: any readiness review still awaiting
    a verdict against it is automatically rejected (PRD §3.6).
    """
    authenticate(["PlatformAdmin"])
    record = common.get_config(config_id)
    data = common.body()
    if data.get("base_placement_fee_cents") is not None:
        record["base_placement_fee_cents"] = as_int(data.get("base_placement_fee_cents"))
    if data.get("integration_tier") is not None:
        record["integration_tier"] = as_int(data.get("integration_tier"))
    if data.get("max_instrument_lives") is not None:
        record["max_instrument_lives"] = as_int(data.get("max_instrument_lives"))
    if data.get("requires_dark_fiber") is not None:
        record["requires_dark_fiber"] = as_bool(data.get("requires_dark_fiber"))
    if data.get("requires_dedicated_power_circuit") is not None:
        record["requires_dedicated_power_circuit"] = as_bool(
            data.get("requires_dedicated_power_circuit"))
    if data.get("feature_entitlements") is not None:
        record["feature_entitlements"] = as_list(data.get("feature_entitlements"))
    for field in ("min_operating_room_length_cm", "min_operating_room_width_cm",
                  "min_table_throw_radius_cm", "min_ceiling_clearance_cm"):
        if data.get(field) is not None:
            record[field] = as_int(data.get(field))
    if data.get("status") is not None:
        record["status"] = as_str(data.get("status")).strip().upper()
    touch(record)

    # Retirement drives the automatic rejection path (no client trigger).
    if record.get("status") == "RETIRED":
        for review in DB.site_readiness_reviews.values():
            if (review.get("evaluated_configuration_id") == config_id
                    and review.get("readiness_status") == "PENDING_REVIEW"):
                review["readiness_status"] = "REJECTED"
                touch(review)
                account = DB.hospital_accounts.get(review.get("hospital_account_id"))
                if account is not None:
                    account["account_posture"] = calc.account_posture(account)
    return success(ser_config(record))


# ---------------------------------------------------------------------------
# Software releases
# ---------------------------------------------------------------------------

@bp.post("/api/system-configurations/<config_id>/releases")
def create_release(config_id):
    authenticate(["PlatformAdmin"])
    config = common.get_config(config_id)
    data = common.body()
    record = base_record({
        "system_configuration_id": config.get("id"),
        "release_index": common.require_int(data, "release_index"),
        "feature_codes": as_list(data.get("feature_codes")),
        "deployed": False,
    })
    DB.software_releases[record["id"]] = record
    return success(ser_release(record)), 201


@bp.get("/api/software-releases")
def list_releases():
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    records = list(DB.software_releases.values())
    config_id = common.arg("system_configuration_id")
    if config_id:
        records = [r for r in records if r.get("system_configuration_id") == config_id]
    index = common.arg_int("release_index")
    if index is not None:
        records = [r for r in records if int(r.get("release_index") or 0) == index]
    return common.paged(records, "software_releases")


@bp.get("/api/system-configurations/<config_id>/software-releases")
def list_configuration_releases(config_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    common.get_config(config_id)
    records = calc.releases_of_configuration(config_id)
    return common.paged(records, "software_releases")


@bp.get("/api/software-releases/<release_id>")
def get_release(release_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    return success(ser_release(common.get_release(release_id)))


@bp.get("/api/software-deployments")
def list_deployments():
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    records = list(DB.software_deployments.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    release_id = common.arg("software_release_id")
    if release_id:
        records = [r for r in records if r.get("software_release_id") == release_id]
    status = common.arg("deployment_status")
    if status:
        records = [r for r in records if r.get("deployment_status") == status]
    return common.paged(records, "software_deployments")