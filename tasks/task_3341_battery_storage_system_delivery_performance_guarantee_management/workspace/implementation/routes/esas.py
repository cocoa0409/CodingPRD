"""EquipmentSupplyAgreement routes: create/list/get/execute/complete/waive-ld."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from util import (new_id, stamp_new, touch, req_pos_number, req_nonneg_int,
                  req_number, parse_iso, round2, to_number)

bp = Blueprint("esas", __name__)

PERMIT_TYPES = ("THERMAL_RUNAWAY_PLAN", "FIRE_CODE", "LOCAL_APPROVAL")


def serialize_esa(e):
    return dict(e)


def get_esa_or_404(eid):
    e = store.esas.get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "EquipmentSupplyAgreement not found")
    return e


@bp.route("/equipment-supply-agreements", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def create_esa():
    body = request.get_json(silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, str) or project_id not in store.projects:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "project_id does not reference an existing Project")
    project = store.projects[project_id]

    contracted_power = req_pos_number(body, "contracted_power_mw")
    contracted_energy = req_pos_number(body, "contracted_energy_mwh")
    guaranteed_capacity = req_pos_number(body, "guaranteed_capacity_mwh")
    rte = req_number(body, "guaranteed_rte_pct")
    if not (rte > 0 and rte <= 1):
        raise ApiError("ERR_INVALID_REQUEST", 400, "guaranteed_rte_pct must be in (0, 1]")
    price = req_nonneg_int(body, "price_per_mwh_cents")
    ld_rate = req_nonneg_int(body, "ld_rate_per_day_cents")
    ld_cap = req_nonneg_int(body, "ld_cap_cents")
    gdd_raw = body.get("guaranteed_delivery_date")
    longstop_raw = body.get("longstop_date")
    gdd = parse_iso(gdd_raw, "guaranteed_delivery_date")
    longstop = parse_iso(longstop_raw, "longstop_date")
    if longstop <= gdd:
        raise ApiError("ERR_INVALID_REQUEST", 400, "longstop_date must be strictly after guaranteed_delivery_date")
    if guaranteed_capacity > contracted_energy:
        raise ApiError("ERR_INVALID_REQUEST", 400, "guaranteed_capacity_mwh must be <= contracted_energy_mwh")

    energy_rounded = round2(Decimal(str(contracted_energy)))
    total_price = int(energy_rounded * price)

    e = {
        "id": new_id(),
        "project_id": project_id,
        "contracted_power_mw": contracted_power,
        "contracted_energy_mwh": contracted_energy,
        "guaranteed_capacity_mwh": guaranteed_capacity,
        "guaranteed_rte_pct": rte,
        "price_per_mwh_cents": price,
        "total_price_cents": total_price,
        "ld_rate_per_day_cents": ld_rate,
        "ld_cap_cents": ld_cap,
        "accrued_ld_cents": 0,
        "waived_ld_cents": 0,
        "net_ld_due_cents": 0,
        "guaranteed_delivery_date": gdd_raw,
        "longstop_date": longstop_raw,
        "status": "DRAFT",
    }
    stamp_new(e)
    store.esas[e["id"]] = e
    return success_object(serialize_esa(e), 201)


@bp.route("/equipment-supply-agreements", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_esas():
    project_id = request.args.get("project_id")
    items = [e for e in store.esas.values()
             if project_id is None or e["project_id"] == project_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_esa(e) for e in page], limit, offset, total)


@bp.route("/equipment-supply-agreements/<eid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_esa(eid):
    return success_object(serialize_esa(get_esa_or_404(eid)))


@bp.route("/equipment-supply-agreements/<eid>/execute", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def execute_esa(eid):
    e = get_esa_or_404(eid)
    project = store.projects.get(e["project_id"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_project_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "expected_project_version must be an integer")
        if expected != project["version"]:
            raise ApiError("ERR_STALE_PROJECT_VERSION", 412,
                           "expected_project_version does not equal the Project's current version")
    # state
    if e["status"] != "DRAFT":
        raise ApiError("ERR_ESA_NOT_DRAFT", 409, "ESA execute requires DRAFT")
    # safety gating: all three permit types APPROVED
    approved_types = {p["permit_type"] for p in store.permits.values()
                      if p["project_id"] == project["id"] and p["status"] == "APPROVED"}
    if any(t not in approved_types for t in PERMIT_TYPES):
        raise ApiError("ERR_PERMIT_MISSING_OR_UNAPPROVED", 409,
                       "Not all three permit types are APPROVED for the project")
    # structural
    if project["sizing_status"] != "VALID":
        raise ApiError("ERR_SIZING_INVALID", 409, "Project sizing is INVALID")
    if Decimal(str(e["guaranteed_capacity_mwh"])) > Decimal(str(project["rated_energy_mwh"])):
        raise ApiError("ERR_GUARANTEE_EXCEEDS_RATED_ENERGY", 409,
                       "guaranteed_capacity_mwh exceeds the project's rated_energy_mwh")
    # fiscal
    if e["total_price_cents"] > project["budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 402, "total_price_cents exceeds project budget_cents")

    e["status"] = "EXECUTED"
    touch(e)
    touch(project)  # derived_field_reconciliation hook: parent version +1
    return success_object(serialize_esa(e))


@bp.route("/equipment-supply-agreements/<eid>/complete", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def complete_esa(eid):
    e = get_esa_or_404(eid)
    if e["status"] != "EXECUTED":
        raise ApiError("ERR_ESA_NOT_EXECUTABLE_STATE", 409, "ESA must be EXECUTED")
    milestones = [m for m in store.milestones.values() if m["esa_id"] == e["id"]]
    delivery = [m for m in milestones if m["kind"] == "DELIVERY"]
    if any(m["status"] not in ("ACHIEVED", "CANCELLED") for m in delivery):
        raise ApiError("ERR_DELIVERY_MILESTONES_OPEN", 409,
                       "Every DELIVERY milestone must be ACHIEVED or CANCELLED")
    commissioning = [m for m in milestones if m["kind"] == "COMMISSIONING"]
    if not any(m["status"] == "ACHIEVED" for m in commissioning):
        raise ApiError("ERR_NO_COMMISSIONING_ACHIEVED", 409,
                       "At least one COMMISSIONING milestone must be ACHIEVED")
    e["status"] = "COMPLETED"
    touch(e)
    project = store.projects.get(e["project_id"])
    if project is not None:
        project["commissioned_capacity_mwh"] = e["contracted_energy_mwh"]
        touch(project)
    return success_object(serialize_esa(e))


@bp.route("/equipment-supply-agreements/<eid>/waive-ld", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def waive_ld(eid):
    e = get_esa_or_404(eid)
    if e["status"] == "DRAFT":
        raise ApiError("ERR_ESA_NOT_DRAFT", 409, "waive-ld requires a non-DRAFT ESA")
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be a positive integer")
    if amount > e["accrued_ld_cents"] - e["waived_ld_cents"]:
        raise ApiError("ERR_WAIVER_EXCEEDS_ACCRUED", 402,
                       "Waiver exceeds accrued_ld_cents - waived_ld_cents")
    e["waived_ld_cents"] += amount
    e["net_ld_due_cents"] = e["accrued_ld_cents"] - e["waived_ld_cents"]
    touch(e)
    return success_object(serialize_esa(e))
