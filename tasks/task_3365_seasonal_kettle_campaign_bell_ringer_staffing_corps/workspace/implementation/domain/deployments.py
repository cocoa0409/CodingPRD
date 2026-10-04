"""Disaster canteen deployment under incident command (PRD 3.8)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

COMMAND_LEVELS = ("TYPE_1", "TYPE_2", "TYPE_3", "TYPE_4", "TYPE_5")
DEPLOYMENT_STATUSES = (
    "REQUESTED",
    "APPROVED",
    "STAGED",
    "DEPLOYED",
    "DEMOBILIZED",
    "DENIED",
    "CANCELLED",
)


def refresh_unit_commitment(unit):
    from domain.units import committed_canteen_count

    unit["committed_canteen_count"] = committed_canteen_count(unit["id"])
    store.touch(unit)
    return unit


def uncommitted_pool(unit):
    from domain.units import committed_canteen_count

    return int(unit.get("canteen_pool_size", 0) or 0) - committed_canteen_count(unit["id"])


@bp.route("/disaster-deployments", methods=["POST"])
def create_deployment():
    require_role(["DisasterServicesCoordinator", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("unit_id", validate.STRING, required=True),
            validate.f("incident_name", validate.STRING, required=True),
            validate.f("incident_command_level", validate.ENUM, required=True, enum=COMMAND_LEVELS),
            validate.f("requested_canteens", validate.INTEGER, required=True),
            validate.f("command_authority", validate.STRING, required=True),
        ]
    )
    validate.reference("units", values["unit_id"], "unit")
    deployment = {
        "unit_id": values["unit_id"],
        "incident_name": values["incident_name"],
        "incident_command_level": values["incident_command_level"],
        "requested_canteens": int(values["requested_canteens"]),
        "command_authority": values["command_authority"],
        "status": "REQUESTED",
        "assigned_canteen_count": 0,
        "deployed_at": None,
        "demobilized_at": None,
        "deployment_cost_cents": 0,
    }
    store.insert("disaster_deployments", deployment)
    return success(store.public(deployment)), 201


@bp.route("/disaster-deployments", methods=["GET"])
def list_deployments():
    require_role(
        [
            "PlatformAdmin",
            "DisasterServicesCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
        ]
    )
    args = request.args
    rows = store.ordered("disaster_deployments")
    for field in ("unit_id", "status", "incident_command_level"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/disaster-deployments/<deployment_id>", methods=["GET"])
def get_deployment(deployment_id):
    require_role(
        [
            "PlatformAdmin",
            "DisasterServicesCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
        ]
    )
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    deployment["deployment_cost_cents"] = calcs.deployment_cost(deployment)
    return success(store.public(deployment))


@bp.route("/disaster-deployments/<deployment_id>/approve", methods=["POST"])
def approve_deployment(deployment_id):
    require_role(["TerritorialCommander", "PlatformAdmin"])
    values = validate.shape([validate.f("decision", validate.STRING)])
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    decision = (values.get("decision") or "APPROVE").strip().upper()
    if decision not in ("APPROVE", "DENY"):
        raise ApiError("ERR_INVALID_REQUEST", "decision must be APPROVE or DENY.")

    status = deployment.get("status")
    if decision == "DENY":
        if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
        if status != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        deployment["status"] = "DENIED"
        store.touch(deployment)
        return success(store.public(deployment))

    if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    unit = store.find("units", deployment.get("unit_id"))
    if unit is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "The referenced unit does not exist.")
    if uncommitted_pool(unit) < int(deployment.get("requested_canteens", 0) or 0):
        raise ApiError("ERR_CANTEEN_UNAVAILABLE")

    deployment["status"] = "APPROVED"
    deployment["assigned_canteen_count"] = int(deployment.get("requested_canteens", 0) or 0)
    store.touch(deployment)
    refresh_unit_commitment(unit)
    return success(store.public(deployment))


@bp.route("/disaster-deployments/<deployment_id>/stage", methods=["POST"])
def stage_deployment(deployment_id):
    require_role(["DisasterServicesCoordinator", "PlatformAdmin"])
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    status = deployment.get("status")
    if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    deployment["status"] = "STAGED"
    store.touch(deployment)
    return success(store.public(deployment))


@bp.route("/disaster-deployments/<deployment_id>/deploy", methods=["POST"])
def deploy_deployment(deployment_id):
    require_role(["DisasterServicesCoordinator", "PlatformAdmin"])
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    status = deployment.get("status")
    if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "STAGED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if int(deployment.get("assigned_canteen_count", 0) or 0) < 1:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "At least one canteen must be assigned.")
    deployment["status"] = "DEPLOYED"
    deployment["deployed_at"] = clock.now_iso()
    store.touch(deployment)
    return success(store.public(deployment))


@bp.route("/disaster-deployments/<deployment_id>/cancel", methods=["POST"])
def cancel_deployment(deployment_id):
    require_role(["TerritorialCommander", "PlatformAdmin"])
    validate.shape([validate.f("reason", validate.STRING)])
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    status = deployment.get("status")
    if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("APPROVED", "STAGED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    deployment["status"] = "CANCELLED"
    deployment["assigned_canteen_count"] = 0
    store.touch(deployment)
    unit = store.find("units", deployment.get("unit_id"))
    if unit is not None:
        refresh_unit_commitment(unit)
    return success(store.public(deployment))


@bp.route("/disaster-deployments/<deployment_id>/demobilize", methods=["POST"])
def demobilize_deployment(deployment_id):
    require_role(["DisasterServicesCoordinator", "PlatformAdmin"])
    values = validate.shape([validate.f("demobilized_at", validate.DATETIME, required=True)])
    deployment = validate.path_row("disaster_deployments", deployment_id, "disaster deployment")
    status = deployment.get("status")
    if status in ("DENIED", "CANCELLED", "DEMOBILIZED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "DEPLOYED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    deployed_at = clock.parse(deployment.get("deployed_at"))
    demobilized_at = values["demobilized_at"]
    if deployed_at is not None and demobilized_at < deployed_at:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "demobilized_at may not precede deployed_at.")

    deployment["status"] = "DEMOBILIZED"
    deployment["demobilized_at"] = clock.fmt(demobilized_at)
    # The final cost is settled against the canteens that were actually committed,
    # so it is computed before the pool is released.
    deployment["deployment_cost_cents"] = calcs.deployment_cost(deployment)
    deployment["assigned_canteen_count"] = 0
    store.touch(deployment)
    unit = store.find("units", deployment.get("unit_id"))
    if unit is not None:
        refresh_unit_commitment(unit)
    return success(store.public(deployment))
