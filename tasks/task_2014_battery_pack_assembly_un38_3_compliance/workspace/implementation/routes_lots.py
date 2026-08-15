"""CellLot receiving, quarantine, inspection loop and retest (§3.2)."""

from decimal import Decimal

from flask import Blueprint

import db
from domain import (
    new_row, touch, sorted_rows, get_program, get_lot, require_program_open,
    ser_cell_lot, ser_inspection, decrement_risk, INSPECTION_OUTCOMES,
)
from errors import (
    err_lot_not_received, err_lot_not_in_quarantine, err_lot_not_rejected,
    err_soc_out_of_tolerance, err_retest_limit, err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, as_str, as_int, as_decimal, as_enum, round_half_up

bp = Blueprint("cell_lots", __name__)

SOC_TOLERANCE = Decimal("2.0")


def _lots_of(program_id):
    return sorted_rows([r for r in db.cell_lots.values() if r["program_id"] == program_id])


@bp.route("/integration-programs/<programId>/cell-lots", methods=["POST"])
@require_roles("QualityEngineer")
def create_lot(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    lot_code = as_str(req_field(body, "lot_code"), "lot_code")
    cell_count = as_int(req_field(body, "cell_count"), "cell_count")
    if cell_count <= 0:
        raise err_invalid_request("cell_count must be > 0")
    rated_capacity_mah = as_int(
        req_field(body, "rated_capacity_mah"), "rated_capacity_mah"
    )
    if rated_capacity_mah <= 0:
        raise err_invalid_request("rated_capacity_mah must be > 0")
    receiving_soc = as_decimal(
        req_field(body, "receiving_soc_percent"), "receiving_soc_percent"
    )
    if receiving_soc < 0 or receiving_soc > 100:
        raise err_invalid_request("receiving_soc_percent must be within 0..100")
    receiving_soc = round_half_up(receiving_soc, 1)
    require_program_open(program)

    row = new_row()
    row.update(
        program_id=program["id"],
        lot_code=lot_code,
        cell_count=cell_count,
        rated_capacity_mah=rated_capacity_mah,
        receiving_soc_percent=receiving_soc,
        measured_soc_percent=None,
        quarantine_cycle_count=0,
        status="RECEIVED",
    )
    db.cell_lots[row["id"]] = row
    return success_created(ser_cell_lot(row))


@bp.route("/integration-programs/<programId>/cell-lots", methods=["GET"])
@require_roles()
def list_lots(actor, programId):
    get_program(programId)
    return success_list(_lots_of(programId), ser_cell_lot)


@bp.route("/integration-programs/<programId>/cell-lots/<lotId>", methods=["GET"])
@require_roles()
def get_one_lot(actor, programId, lotId):
    get_program(programId)
    return success_object(ser_cell_lot(get_lot(programId, lotId)))


@bp.route("/integration-programs/<programId>/cell-lots/<lotId>/quarantine", methods=["POST"])
@require_roles("QualityEngineer")
def quarantine_lot(actor, programId, lotId):
    program = get_program(programId)
    lot = get_lot(programId, lotId)
    get_body()
    require_program_open(program)
    if lot["status"] != "RECEIVED":
        raise err_lot_not_received()
    lot["status"] = "QUARANTINE"
    touch(lot)
    return success_object(ser_cell_lot(lot))


@bp.route("/integration-programs/<programId>/cell-lots/<lotId>/inspections", methods=["POST"])
@require_roles("QualityEngineer")
def record_inspection(actor, programId, lotId):
    program = get_program(programId)
    lot = get_lot(programId, lotId)
    body = get_body(required=True)
    measured_soc = as_decimal(
        req_field(body, "measured_soc_percent"), "measured_soc_percent"
    )
    if measured_soc < 0 or measured_soc > 100:
        raise err_invalid_request("measured_soc_percent must be within 0..100")
    measured_soc = round_half_up(measured_soc, 1)
    measured_voltage = round_half_up(
        as_decimal(req_field(body, "measured_voltage_v"), "measured_voltage_v"), 2
    )
    visual_defects = as_int(
        req_field(body, "visual_defect_count"), "visual_defect_count"
    )
    if visual_defects < 0:
        raise err_invalid_request("visual_defect_count must be >= 0")
    outcome = as_enum(req_field(body, "outcome"), "outcome", INSPECTION_OUTCOMES)

    require_program_open(program)
    if lot["status"] != "QUARANTINE":
        raise err_lot_not_in_quarantine()

    if outcome == "PASS":
        # acceptance requires the measured SOC to corroborate the declared
        # receiving SOC within ±2.0 percentage points (priority 8)
        if abs(measured_soc - lot["receiving_soc_percent"]) > SOC_TOLERANCE:
            raise err_soc_out_of_tolerance()
        lot["status"] = "ACCEPTED"
        lot["measured_soc_percent"] = measured_soc
        touch(lot)
    elif outcome == "FAIL_HARD":
        lot["status"] = "REJECTED"
        touch(lot)
        decrement_risk(program, 3)
    else:  # FAIL_SOFT — inconclusive self-loop
        lot["quarantine_cycle_count"] += 1
        touch(lot)

    rec = new_row(common=False)
    rec.update(
        cell_lot_id=lot["id"],
        program_id=program["id"],
        inspector_id=actor.user_id,
        measured_soc_percent=measured_soc,
        measured_voltage_v=measured_voltage,
        visual_defect_count=visual_defects,
        outcome=outcome,
    )
    db.inspections[rec["id"]] = rec
    return success_created(ser_inspection(rec))


@bp.route("/integration-programs/<programId>/cell-lots/<lotId>/inspections", methods=["GET"])
@require_roles()
def list_inspections(actor, programId, lotId):
    get_program(programId)
    lot = get_lot(programId, lotId)
    rows = sorted_rows(
        [r for r in db.inspections.values() if r["cell_lot_id"] == lot["id"]]
    )
    return success_list(rows, ser_inspection)


@bp.route("/integration-programs/<programId>/cell-lots/<lotId>/retest", methods=["POST"])
@require_roles("QualityEngineer")
def retest_lot(actor, programId, lotId):
    program = get_program(programId)
    lot = get_lot(programId, lotId)
    get_body()
    require_program_open(program)
    if lot["status"] != "REJECTED":
        raise err_lot_not_rejected()
    if lot["quarantine_cycle_count"] >= 2:
        raise err_retest_limit()
    lot["status"] = "QUARANTINE"
    lot["quarantine_cycle_count"] += 1
    touch(lot)
    return success_object(ser_cell_lot(lot))
