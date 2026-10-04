"""Robot systems, instrument administration and software deployment."""

from flask import Blueprint

from db import DB, base_record, check_version, to_iso, touch
from errors import ApiError
from middleware import authenticate, check_region
from response import success
from routes import common
from serializers import (robot_system as ser_system,
                         software_deployment as ser_deployment,
                         utilization_cycle as ser_cycle)
from services import calc, machines

bp = Blueprint("systems", __name__)


@bp.get("/api/robot-systems")
def list_systems():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ServiceEngineer",
                  "AccountOwner"])
    records = list(DB.robot_systems.values())
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    agreement_id = common.arg("placement_agreement_id")
    if agreement_id:
        records = [r for r in records if r.get("placement_agreement_id") == agreement_id]
    status = common.arg("service_status")
    if status:
        records = [r for r in records if r.get("service_status") == status]
    config_id = common.arg("system_configuration_id")
    if config_id:
        records = [r for r in records if r.get("system_configuration_id") == config_id]
    review_id = common.arg("site_readiness_review_id")
    if review_id:
        records = [r for r in records if r.get("site_readiness_review_id") == review_id]
    cycle_id = common.arg("current_utilization_cycle_id")
    if cycle_id:
        records = [r for r in records if r.get("current_utilization_cycle_id") == cycle_id]
    return common.paged(records, "robot_systems")


@bp.get("/api/robot-systems/<system_id>")
def get_system(system_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ServiceEngineer",
                  "AccountOwner", "ClinicalOperationsLead"])
    return success(ser_system(common.get_system(system_id)))


@bp.post("/api/robot-systems/<system_id>/install")
def install_system(system_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
    review = DB.site_readiness_reviews.get(system.get("site_readiness_review_id"))
    data = common.body()
    if system.get("service_status") != "NOT_INSTALLED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    check_version(system, data, "expected_robot_system_version")
    machines.system_install(system, account, agreement, review)
    return success(ser_system(system))


@bp.post("/api/robot-systems/<system_id>/commission")
def commission_system(system_id):
    ctx = authenticate(["ClinicalOperationsLead"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
    data = common.body()
    if system.get("service_status") != "INSTALLED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    check_version(system, data, "expected_robot_system_version")
    machines.system_commission(system, account, agreement)
    return success(ser_system(system))


@bp.post("/api/robot-systems/<system_id>/open-service-action")
def open_service_action(system_id):
    ctx = authenticate(["ServiceEngineer"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if system.get("service_status") != "IN_SERVICE":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    check_version(system, data, "expected_robot_system_version")
    machines.system_open_service_action(system, account)
    return success(ser_system(system))


@bp.post("/api/robot-systems/<system_id>/restore-service")
def restore_service(system_id):
    ctx = authenticate(["ServiceEngineer"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    if system.get("service_status") != "SERVICE_ACTION_REQUIRED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    check_version(system, data, "expected_robot_system_version")
    machines.system_restore_service(system, account)
    return success(ser_system(system))


@bp.post("/api/robot-systems/<system_id>/decommission")
def decommission_system(system_id):
    authenticate(["PlatformAdmin"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    data = common.body()
    if system.get("service_status") not in ("IN_SERVICE", "INSTALLED"):
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    check_version(system, data, "expected_robot_system_version")
    machines.system_decommission(system, account)
    return success(ser_system(system))


# ---------------------------------------------------------------------------
# Instrument administration
# ---------------------------------------------------------------------------

@bp.post("/api/robot-systems/<system_id>/instrument-lives/decrement")
def decrement_instrument_lives(system_id):
    """Post a manual instrument-and-accessory load against the accessory set."""
    ctx = authenticate(["ServiceEngineer"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    load = common.require_int(data, "approved_load")
    if load < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    entry = base_record({
        "robot_system_id": system.get("id"),
        "approved_load": load,
        "posted_at_utc": to_iso(DB.clock),
    })
    system.setdefault("_accessory_load_ledger", []).append(entry)
    system["_manual_decrement_total"] = int(system.get("_manual_decrement_total") or 0) + load
    machines.refresh_system(system)
    touch(system)
    return success(ser_system(system))


@bp.post("/api/robot-systems/<system_id>/instrument-lives/reset")
def reset_instrument_lives(system_id):
    """Provision a replacement accessory set — the only action that raises the
    remaining lives."""
    ctx = authenticate(["ServiceEngineer"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    check_version(system, data, "expected_robot_system_version")
    # The fresh set discards everything consumed up to this instant; the watermark
    # is the sequence number of the provisioning entry itself, so consumption
    # recorded after it still draws the new set down.
    provisioning = base_record({
        "robot_system_id": system.get("id"),
        "approved_load": 0,
        "posted_at_utc": to_iso(DB.clock),
    })
    system.setdefault("_accessory_load_ledger", []).append(provisioning)
    system["_lives_watermark"] = provisioning["_seq"]
    system.pop("_replacement_provisioned", None)
    machines.refresh_system(system)
    touch(system)
    return success(ser_system(system))


# ---------------------------------------------------------------------------
# Software deployments
# ---------------------------------------------------------------------------

@bp.post("/api/robot-systems/<system_id>/software-deployments")
def program_deployment(system_id):
    ctx = authenticate(["ServiceEngineer"])
    system = common.get_system(system_id)
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    data = common.body()
    release = common.get_release(common.require_str(data, "software_release_id"))
    window_start = common.require_dt(data, "scheduled_window_start_utc")
    window_end = common.require_dt(data, "scheduled_window_end_utc")
    # Priority 26 — the release must target the system's own configuration.
    if release.get("system_configuration_id") != system.get("system_configuration_id"):
        raise ApiError("ERR_RELEASE_CONFIGURATION_MISMATCH")
    # Priority 31 — the release index must be strictly above what is installed.
    if int(release.get("release_index") or 0) <= int(system.get("installed_software_release_index") or 0):
        raise ApiError("ERR_RELEASE_DOWNGRADE")
    # Priority 30 — a zero-length window is accepted, a negative one is not.
    if window_end < window_start:
        raise ApiError("ERR_INVALID_WINDOW")
    # Priority 34 — the window start must not precede the creation instant.
    if window_start < DB.clock:
        raise ApiError("ERR_DEPLOYMENT_WINDOW_INVALID")
    record = base_record({
        "robot_system_id": system.get("id"),
        "software_release_id": release.get("id"),
        "deployment_status": "PROGRAMMED",
        "scheduled_window_start_utc": to_iso(window_start),
        "scheduled_window_end_utc": to_iso(window_end),
        "entitlement_snapshot": [],
    })
    DB.software_deployments[record["id"]] = record
    return success(ser_deployment(record)), 201


@bp.get("/api/robot-systems/<system_id>/software-deployments")
def list_system_deployments(system_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    common.get_system(system_id)
    records = calc.deployments_of_system(system_id)
    status = common.arg("deployment_status")
    if status:
        records = [r for r in records if r.get("deployment_status") == status]
    return common.paged(records, "software_deployments")


@bp.get("/api/software-deployments/<deployment_id>")
def get_deployment(deployment_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    return success(ser_deployment(common.get_deployment(deployment_id)))


@bp.post("/api/software-deployments/<deployment_id>/complete")
def complete_deployment(deployment_id):
    """Complete a deployment and reconcile the system's feature entitlements."""
    authenticate(["ServiceEngineer"])
    deployment = common.get_deployment(deployment_id)
    system = common.get_system(deployment.get("robot_system_id"))
    data = common.body()
    if deployment.get("deployment_status") != "PROGRAMMED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(deployment, data, "expected_deployment_version")
    release = DB.software_releases.get(deployment.get("software_release_id"))
    deployment["deployment_status"] = "COMPLETED"
    if release is not None:
        release["deployed"] = True
        touch(release)
        system["installed_software_release_index"] = max(
            int(system.get("installed_software_release_index") or 0),
            int(release.get("release_index") or 0))
    config = DB.system_configurations.get(system.get("system_configuration_id"))
    index = int(system.get("installed_software_release_index") or 0)
    snapshot = calc.entitled_feature_codes(config, index)
    deployment["entitlement_snapshot"] = snapshot
    system["entitled_feature_codes"] = snapshot
    touch(deployment)
    machines.refresh_system(system)
    touch(system)
    return success(ser_deployment(deployment))


# ---------------------------------------------------------------------------
# Utilization cycles
# ---------------------------------------------------------------------------

@bp.get("/api/robot-systems/<system_id>/utilization-cycles")
def list_system_cycles(system_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "AccountOwner"])
    common.get_system(system_id)
    return common.paged(calc.cycles_of_system(system_id), "utilization_cycles")


@bp.get("/api/robot-systems/<system_id>/current-utilization-cycle")
def current_cycle(system_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "AccountOwner",
                  "ClinicalOperationsLead"])
    system = common.get_system(system_id)
    cycle = calc.current_cycle(system)
    if cycle is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return success(ser_cycle(cycle))


@bp.get("/api/utilization-cycles")
def list_cycles():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "AccountOwner"])
    records = list(DB.utilization_cycles.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    agreement_id = common.arg("placement_agreement_id")
    if agreement_id:
        records = [r for r in records if r.get("placement_agreement_id") == agreement_id]
    return common.paged(records, "utilization_cycles")


@bp.get("/api/utilization-cycles/<cycle_id>")
def get_cycle(cycle_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "AccountOwner"])
    return success(ser_cycle(common.get_cycle(cycle_id)))