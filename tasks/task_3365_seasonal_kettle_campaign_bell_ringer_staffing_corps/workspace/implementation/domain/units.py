"""Units: the organizational hierarchy (PRD 2.4)."""
from flask import request

from core import store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

UNIT_TYPES = ("CORPS", "DIVISION", "AREA_COMMAND", "TERRITORY")


def oversight_level_for(parent_unit_id, seen=None):
    """Depth of the unit in the parent chain; TERRITORY = 0."""
    if not parent_unit_id:
        return 0
    seen = seen or set()
    if parent_unit_id in seen:
        return 0
    seen.add(parent_unit_id)
    parent = store.find("units", parent_unit_id)
    if parent is None:
        return 0
    return 1 + oversight_level_for(parent.get("parent_unit_id"), seen)


def committed_canteen_count(unit_id):
    total = 0
    for deployment in store.rows("disaster_deployments"):
        if deployment.get("unit_id") != unit_id:
            continue
        if deployment.get("status") in ("APPROVED", "STAGED", "DEPLOYED"):
            total += int(deployment.get("assigned_canteen_count", 0) or 0)
    return total


def recompute_unit(unit):
    unit["committed_canteen_count"] = committed_canteen_count(unit["id"])
    unit["oversight_level"] = oversight_level_for(unit.get("parent_unit_id"))
    store.touch(unit)
    return unit


def unit_body(unit):
    return store.public(unit)


@bp.route("/units", methods=["POST"])
def create_unit():
    require_role(["PlatformAdmin", "TerritorialCommander"])
    values = validate.shape(
        [
            validate.f("name", validate.STRING, required=True),
            validate.f("unit_type", validate.ENUM, required=True, enum=UNIT_TYPES),
            validate.f("parent_unit_id", validate.STRING),
            validate.f("territory_code", validate.STRING, required=True),
            validate.f("canteen_pool_size", validate.INTEGER),
        ]
    )
    parent_id = values.get("parent_unit_id")
    if parent_id:
        validate.reference("units", parent_id, "parent unit")

    unit = {
        "name": values["name"],
        "unit_type": values["unit_type"],
        "parent_unit_id": parent_id or None,
        "territory_code": values["territory_code"],
        "canteen_pool_size": int(values.get("canteen_pool_size", 0) or 0),
        "committed_canteen_count": 0,
        "oversight_level": 0,
    }
    store.insert("units", unit)
    unit["oversight_level"] = oversight_level_for(unit.get("parent_unit_id"))
    return success(unit_body(unit)), 201


@bp.route("/units", methods=["GET"])
def list_units():
    require_role(
        [
            "PlatformAdmin",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "ProgramDirector",
            "DisasterServicesCoordinator",
        ]
    )
    args = request.args
    rows = store.ordered("units")
    unit_type = args.get("unit_type")
    parent_unit_id = args.get("parent_unit_id")
    territory_code = args.get("territory_code")
    if unit_type:
        rows = [r for r in rows if r.get("unit_type") == unit_type]
    if parent_unit_id:
        rows = [r for r in rows if r.get("parent_unit_id") == parent_unit_id]
    if territory_code:
        rows = [r for r in rows if r.get("territory_code") == territory_code]
    return page([store.public(r) for r in rows], args)


@bp.route("/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    require_role(
        [
            "PlatformAdmin",
            "TerritorialCommander",
            "DivisionalOfficer",
            "CorpsOfficer",
            "ProgramDirector",
            "DisasterServicesCoordinator",
            "AssistanceCaseworker",
        ]
    )
    unit = validate.path_row("units", unit_id, "unit")
    return success(store.public(unit))
