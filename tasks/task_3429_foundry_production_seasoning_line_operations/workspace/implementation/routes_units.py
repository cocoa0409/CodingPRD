"""Casting unit endpoints: list/get, inspect, complete-rework, per-unit defect reports (PRD 3.5)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from errors import err
from validate import paginate_params, parse_body, validate, validate_no_fields

bp = Blueprint("units", __name__)

DEFECT_TYPES = ["POROSITY", "COLD_SHUT", "MISRUN", "SAND_INCLUSION", "DIMENSIONAL", "CRACK"]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]


@bp.route("/foundry/casting-units", methods=["GET"])
def list_units():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["units"].values())
    for param in ("production_order_id", "melt_batch_id", "mold_id", "seasoning_batch_id", "state"):
        v = request.args.get(param)
        if v is not None:
            items = [u for u in items if u.get(param) == v]
    return envelope.list_payload(items, serialize.casting_unit, limit, offset)


@bp.route("/foundry/casting-units/<uid>", methods=["GET"])
def get_unit(uid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    u = domain.get_or_404("units", uid)
    return envelope.success(serialize.casting_unit(u))


@bp.route("/foundry/casting-units/<uid>/inspect", methods=["POST"])
def inspect_unit(uid):
    _uid, role = authenticate()
    authorize(role, ["QualityInspector"])
    body = parse_body()
    vals = validate(
        body,
        [
            {"name": "outcome", "kind": "enum", "values": ["PASS", "DEFECT"]},
            {"name": "measured_weight_oz", "kind": "number"},
            {"name": "measured_diameter_in", "kind": "number"},
            {"name": "measured_wall_thickness_in", "kind": "number"},
            {"name": "defect_type", "kind": "enum", "values": DEFECT_TYPES, "required": False},
            {"name": "severity", "kind": "enum", "values": SEVERITIES, "required": False},
            {"name": "notes", "kind": "string", "required": False},
        ],
    )
    if vals["outcome"] == "DEFECT":
        if "defect_type" not in vals or "severity" not in vals:
            raise err(
                "ERR_INVALID_REQUEST",
                "defect_type and severity are required when outcome is DEFECT",
            )
    u = domain.get_or_404("units", uid)
    if u["state"] != "SHAKEOUT_DONE":
        raise err("ERR_INVALID_STATE_TRANSITION", "unit is not SHAKEOUT_DONE")

    order = store.db["orders"][u["production_order_id"]]
    product = store.db["products"][order["product_id"]]

    if vals["outcome"] == "PASS":
        if (
            abs(vals["measured_weight_oz"] - calc.D(product["target_weight_oz"]))
            > calc.D(product["weight_tolerance_oz"])
            or abs(vals["measured_diameter_in"] - calc.D(product["target_diameter_in"]))
            > calc.D(product["diameter_tolerance_in"])
            or vals["measured_wall_thickness_in"] < calc.D(product["min_wall_thickness_in"])
        ):
            raise err("ERR_TOLERANCE_EXCEEDED", "measurements outside product tolerances")
        u["measured_weight_oz"] = vals["measured_weight_oz"]
        u["measured_diameter_in"] = vals["measured_diameter_in"]
        u["measured_wall_thickness_in"] = vals["measured_wall_thickness_in"]
        domain.mark_unit_finished(u)
        return envelope.success(serialize.casting_unit(u))

    # outcome == DEFECT
    report = store.make_entity()
    report.update(
        {
            "casting_unit_id": u["id"],
            "defect_type": vals["defect_type"],
            "severity": vals["severity"],
            "status": "OPEN",
            "disposition": None,
            "dispositioned_by": None,
            "notes": vals.get("notes"),
        }
    )
    store.db["reports"][report["id"]] = report
    u["measured_weight_oz"] = vals["measured_weight_oz"]
    u["measured_diameter_in"] = vals["measured_diameter_in"]
    u["measured_wall_thickness_in"] = vals["measured_wall_thickness_in"]
    u["state"] = "DEFECT_REVIEW"
    store.touch(u)
    return envelope.success(serialize.casting_unit(u))


@bp.route("/foundry/casting-units/<uid>/complete-rework", methods=["POST"])
def complete_rework(uid):
    _uid, role = authenticate()
    authorize(role, ["MeltOperator"])
    validate_no_fields()
    u = domain.get_or_404("units", uid)
    if u["state"] != "REWORK":
        raise err("ERR_INVALID_STATE_TRANSITION", "unit is not in REWORK")
    u["state"] = "SHAKEOUT_DONE"
    store.touch(u)
    return envelope.success(serialize.casting_unit(u))


@bp.route("/foundry/casting-units/<uid>/defect-reports", methods=["GET"])
def list_unit_defect_reports(uid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    domain.get_or_404("units", uid)
    limit, offset = paginate_params()
    items = [r for r in store.db["reports"].values() if r["casting_unit_id"] == uid]
    return envelope.list_payload(items, serialize.defect_report, limit, offset)
