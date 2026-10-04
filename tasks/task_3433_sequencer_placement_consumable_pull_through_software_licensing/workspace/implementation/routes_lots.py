"""Reagent lot endpoints: registration, reads, QC verdicts with cascades."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles
from cascades import reallocation_sweep, release_lot_reservations_and_backorder
from envelope import ok, ok_list, sort_items
from errors import invalid_state, not_found
from serializers import lot_json
from store import DB, new_id, stamp_new, touch
from validate import f_dt, f_enum, f_int, f_str, get_body, resolve_ref

bp = Blueprint("lots", __name__)

QC_OUTCOMES = ["PASSED", "FAILED", "COLD_CHAIN_BREACH"]


@bp.post("/genomics/reagent-lots")
def create_lot():
    require_roles("SupplyPlanner")
    body = get_body()
    resolve_ref(body, "kit_id", "kits")
    kit_id = f_str(body, "kit_id")
    lot_number = f_str(body, "lot_number")
    manufacture_date = f_dt(body, "manufacture_date")
    quantity_units = f_int(body, "quantity_units", min_v=1)
    kit = DB["kits"][kit_id]
    lot = {
        "id": new_id(),
        "kit_id": kit_id,
        "lot_number": lot_number,
        "manufacture_date": manufacture_date,
        "quantity_units": quantity_units,
        "qc_status": "PENDING_QC",
        "cold_chain_status": "INTACT",
        "expiry_date": manufacture_date + timedelta(days=kit["shelf_life_days"]),
        "reserved_units": 0,
        "consumed_units": 0,
    }
    stamp_new(lot)
    DB["lots"][lot["id"]] = lot
    return ok(lot_json(lot), 201)


@bp.get("/genomics/reagent-lots/<lot_id>")
def get_lot(lot_id):
    require_roles("SupplyPlanner", "LabOperator")
    lot = DB["lots"].get(lot_id)
    if lot is None:
        raise not_found("ReagentLot not found")
    return ok(lot_json(lot))


@bp.get("/genomics/reagent-lots")
def list_lots():
    require_roles("SupplyPlanner", "LabOperator")
    items = list(DB["lots"].values())
    kit_id = request.args.get("kit_id")
    qc_status = request.args.get("qc_status")
    if kit_id is not None:
        items = [l for l in items if l["kit_id"] == kit_id]
    if qc_status is not None:
        items = [l for l in items if l["qc_status"] == qc_status]
    return ok_list([lot_json(l) for l in sort_items(items)])


@bp.post("/genomics/reagent-lots/<lot_id>/qc")
def lot_qc(lot_id):
    require_roles("SupplyPlanner")
    lot = DB["lots"].get(lot_id)
    if lot is None:
        raise not_found("ReagentLot not found")
    body = get_body()
    outcome = f_enum(body, "outcome", QC_OUTCOMES)
    state = lot["qc_status"]
    if outcome == "PASSED":
        if state != "PENDING_QC":
            raise invalid_state("PASSED requires qc_status PENDING_QC")
        lot["qc_status"] = "QC_PASSED"
        touch(lot)
        reallocation_sweep()
    elif outcome == "FAILED":
        if state == "PENDING_QC":
            lot["qc_status"] = "QC_FAILED"  # terminal, no cascade
            touch(lot)
        elif state == "QC_PASSED":
            # Field corrective action: release reservations and backorder.
            lot["qc_status"] = "QC_FAILED"
            release_lot_reservations_and_backorder(lot)
            touch(lot)
        else:
            raise invalid_state("FAILED requires qc_status PENDING_QC or QC_PASSED")
    else:  # COLD_CHAIN_BREACH — self-transition, reservations kept
        if state not in ("PENDING_QC", "QC_PASSED"):
            raise invalid_state("COLD_CHAIN_BREACH requires PENDING_QC or QC_PASSED")
        lot["cold_chain_status"] = "BREACHED"
        touch(lot)
    return ok(lot_json(lot))
