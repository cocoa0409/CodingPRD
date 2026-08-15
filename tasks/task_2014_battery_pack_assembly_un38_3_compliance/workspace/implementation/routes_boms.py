"""PackBOM definition (§3.3)."""

from flask import Blueprint, request

import db
from domain import (
    new_row, sorted_rows, get_program, get_bom, require_program_open,
    ser_bom, compute_nominal_energy_wh, locked_committed_cells, WELD_PROFILES,
)
from errors import (
    err_lot_not_found, err_cross_program, err_lot_not_accepted, err_lot_depleted,
    err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, opt_field, as_str, as_int, as_enum

bp = Blueprint("pack_boms", __name__)


@bp.route("/integration-programs/<programId>/pack-boms", methods=["POST"])
@require_roles("AssemblyLead")
def create_bom(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    bom_code = as_str(req_field(body, "bom_code"), "bom_code")
    cell_lot_id = as_str(req_field(body, "cell_lot_id"), "cell_lot_id")
    cells_required = as_int(req_field(body, "cells_required"), "cells_required")
    if cells_required < 1:
        raise err_invalid_request("cells_required must be >= 1")
    series_count = as_int(req_field(body, "series_count"), "series_count")
    if series_count < 1:
        raise err_invalid_request("series_count must be >= 1")
    parallel_count = as_int(req_field(body, "parallel_count"), "parallel_count")
    if parallel_count < 1:
        raise err_invalid_request("parallel_count must be >= 1")
    welding_profile = as_enum(
        req_field(body, "welding_profile"), "welding_profile", WELD_PROFILES
    )
    version_note = opt_field(body, "version_note")
    if version_note is not None and not isinstance(version_note, str):
        raise err_invalid_request("version_note must be a string")

    lot = db.cell_lots.get(cell_lot_id)
    if lot is None:
        raise err_lot_not_found()
    require_program_open(program)
    # priority 12: cross-program referential integrity
    if lot["program_id"] != program["id"]:
        raise err_cross_program()
    # priority 13: lot acceptance and remaining capacity
    if lot["status"] == "DEPLETED":
        raise err_lot_depleted()
    if lot["status"] != "ACCEPTED":
        raise err_lot_not_accepted()
    if locked_committed_cells(lot["id"]) + cells_required > lot["cell_count"]:
        raise err_lot_depleted()

    row = new_row()
    row.update(
        program_id=program["id"],
        bom_code=bom_code,
        cell_lot_id=lot["id"],
        cells_required=cells_required,
        series_count=series_count,
        parallel_count=parallel_count,
        nominal_energy_wh=compute_nominal_energy_wh(cells_required, lot["rated_capacity_mah"]),
        welding_profile=welding_profile,
        is_locked=False,
        version_note=version_note,
    )
    db.boms[row["id"]] = row
    return success_created(ser_bom(row))


@bp.route("/integration-programs/<programId>/pack-boms", methods=["GET"])
@require_roles()
def list_boms(actor, programId):
    get_program(programId)
    rows = [r for r in db.boms.values() if r["program_id"] == programId]
    cell_lot_id = request.args.get("cell_lot_id")
    if cell_lot_id is not None:
        rows = [r for r in rows if r["cell_lot_id"] == cell_lot_id]
    return success_list(sorted_rows(rows), ser_bom)


@bp.route("/integration-programs/<programId>/pack-boms/<bomId>", methods=["GET"])
@require_roles()
def get_one_bom(actor, programId, bomId):
    get_program(programId)
    return success_object(ser_bom(get_bom(programId, bomId)))
