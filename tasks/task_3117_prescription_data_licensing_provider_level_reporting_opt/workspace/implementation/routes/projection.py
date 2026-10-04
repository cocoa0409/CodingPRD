"""ProjectionMethodology and ProjectionCell endpoints."""

from flask import Blueprint, request

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_stale_version,
)
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.calculations import calc_market_projection
from services.cascades import recall_deliveries_for_cell
from services.common import (
    body_json, require_fields, check_str, check_int, check_num, check_enum, check_period,
    check_str_list, mint, touch,
)

bp = Blueprint("projection", __name__)

VARIANTS = {"PROJECTION_WEIGHTED", "PROJECTION_DENSITY"}
SPECIALTIES = {"CARDIOLOGY", "ONCOLOGY", "ENDOCRINOLOGY", "PRIMARY_CARE"}
CELL_STATUSES = {"CURRENT", "PENDING_RESTATEMENT"}


# ---------------- Methodologies ----------------

@bp.route("/projection-methodologies", methods=["POST"])
def create_methodology():
    require_role(["PlatformAdmin"])
    data = body_json()
    require_fields(data, ["name", "default_variant"])
    methodology = mint(db.methodologies, {
        "name": check_str(data, "name"),
        "default_variant": check_enum(data, "default_variant", VARIANTS),
        "status": "ACTIVE",
    })
    return success_object(methodology, status=201)


@bp.route("/projection-methodologies/<mid>", methods=["GET"])
def get_methodology(mid):
    require_role(ALL_ROLES)
    methodology = db.methodologies.get(mid)
    if methodology is None:
        raise err_not_found("Methodology not found")
    return success_object(methodology)


@bp.route("/projection-methodologies/<mid>/restate", methods=["POST"])
def restate_methodology(mid):
    require_role(["PlatformAdmin"])
    methodology = db.methodologies.get(mid)
    if methodology is None:
        raise err_not_found("Methodology not found")
    data = body_json()
    require_fields(data, ["expected_methodology_version"])
    if data["expected_methodology_version"] != methodology["version"]:
        raise err_stale_version()
    touch(methodology)
    for cell in sorted(db.projection_cells.values(), key=lambda c: c["created_at"]):
        if cell["methodology_id"] == mid and cell["status"] == "CURRENT":
            cell["status"] = "PENDING_RESTATEMENT"
            touch(cell)
            recall_deliveries_for_cell(cell)
    return success_object(methodology)


# ---------------- Projection cells ----------------

@bp.route("/projection-cells", methods=["POST"])
def create_cell():
    require_role(["PlatformAdmin"])
    data = body_json()
    require_fields(data, [
        "methodology_id", "geography_code", "specialty", "period_code",
        "sample_units", "market_outlets", "sampled_outlets",
        "market_population", "sampled_population", "specialty_uptake_index",
        "supplier_ids",
    ])
    methodology_id = check_str(data, "methodology_id")
    if methodology_id not in db.methodologies:
        raise err_not_found("Methodology not found")
    geography_code = check_str(data, "geography_code")
    specialty = check_enum(data, "specialty", SPECIALTIES)
    period_code = check_period(data, "period_code")
    sample_units = check_int(data, "sample_units", min_v=0)
    market_outlets = check_int(data, "market_outlets", min_v=1)
    sampled_outlets = check_int(data, "sampled_outlets", min_v=1)
    market_population = check_int(data, "market_population", min_v=1)
    sampled_population = check_int(data, "sampled_population", min_v=1)
    uptake = check_num(data, "specialty_uptake_index", gt=0)
    supplier_ids = check_str_list(data, "supplier_ids")
    for sid in supplier_ids:
        if sid not in db.suppliers:
            raise err_not_found("Supplier not found")
    cell = mint(db.projection_cells, {
        "methodology_id": methodology_id,
        "geography_code": geography_code,
        "specialty": specialty,
        "period_code": period_code,
        "sample_units": sample_units,
        "market_outlets": market_outlets,
        "sampled_outlets": sampled_outlets,
        "market_population": market_population,
        "sampled_population": sampled_population,
        "specialty_uptake_index": uptake,
        "supplier_ids": list(supplier_ids),
        "estimate_units": None,
        "restatement_delta_units": None,
        "status": "CURRENT",
    })
    return success_object(cell, status=201)


@bp.route("/projection-cells", methods=["GET"])
def list_cells():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    methodology_id = request.args.get("methodology_id")
    geography_code = request.args.get("geography_code")
    status = request.args.get("status")
    if status is not None and status not in CELL_STATUSES:
        raise err_invalid_request("Invalid status filter")
    items = sorted(db.projection_cells.values(), key=lambda c: c["created_at"])
    if methodology_id is not None:
        items = [c for c in items if c["methodology_id"] == methodology_id]
    if geography_code is not None:
        items = [c for c in items if c["geography_code"] == geography_code]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/projection-cells/<cid>", methods=["GET"])
def get_cell(cid):
    require_role(ALL_ROLES)
    cell = db.projection_cells.get(cid)
    if cell is None:
        raise err_not_found("Projection cell not found")
    return success_object(cell)


@bp.route("/projection-cells/<cid>/recompute", methods=["POST"])
def recompute_cell(cid):
    require_role(["PlatformAdmin"])
    cell = db.projection_cells.get(cid)
    if cell is None:
        raise err_not_found("Projection cell not found")
    data = body_json()
    require_fields(data, ["projection_variant"])
    variant = check_enum(data, "projection_variant", VARIANTS)
    new_sampled_outlets = None
    if "sampled_outlets" in data and data["sampled_outlets"] is not None:
        new_sampled_outlets = check_int(data, "sampled_outlets", min_v=1)
    if cell["status"] not in ("CURRENT", "PENDING_RESTATEMENT"):
        raise err_invalid_state("Cell state does not permit recompute")
    previous = cell["estimate_units"]
    if new_sampled_outlets is not None:
        cell["sampled_outlets"] = new_sampled_outlets
    estimate = calc_market_projection(cell, variant)
    cell["estimate_units"] = estimate
    cell["restatement_delta_units"] = None if previous is None else estimate - previous
    cell["status"] = "CURRENT"
    touch(cell)
    return success_object(cell)
