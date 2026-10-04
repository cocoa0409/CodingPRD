"""FeedstockLot endpoints (PRD 3.2): intake, QC, allocate/deallocate."""
from flask import Blueprint, request

from auth import authenticate, authorize
from calcs import recompute_batch, supplier_reliability
from constants import ALL_ROLES, QC_OUTCOMES, SOURCE_TYPES
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_lot
from store import STORE, new_common, touch
from util import get_body, req_decimal, req_enum, req_str

bp = Blueprint("feedstock", __name__)


@bp.route("/carpetloop/feedstock-lots", methods=["POST"])
def create_lot():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    # Priority 11: request shape.
    supplier_name = req_str(body, "supplier_name")
    source_type = req_enum(body, "source_type", SOURCE_TYPES)
    quantity_kg = req_decimal(body, "quantity_kg", min_exclusive=0)
    carbon_factor = req_decimal(body, "carbon_factor_kgco2e_per_kg", min_inclusive=0)
    # supplier_reliability is computed over strictly-prior decided lots of the
    # same supplier_name — evaluate before inserting the new lot.
    reliability = supplier_reliability(STORE, supplier_name)
    lot = new_common(STORE)
    lot.update(
        {
            "supplier_name": supplier_name,
            "source_type": source_type,
            "quantity_kg": quantity_kg,
            "carbon_factor_kgco2e_per_kg": carbon_factor,
            "origin_takeback_id": None,
            "supplier_reliability_pct": reliability,
            "allocated_kg": quantity_kg.__class__("0"),
            "available_kg": quantity_kg,
            "status": "RECEIVED",
        }
    )
    STORE.lots[lot["id"]] = lot
    return success(serialize_lot(lot), 201)


@bp.route("/carpetloop/feedstock-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    lot = STORE.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404, "Feedstock lot does not exist")
    return success(serialize_lot(lot), 200)


@bp.route("/carpetloop/feedstock-lots", methods=["GET"])
def list_lots():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("supplier_name", "source_type", "status", "origin_takeback_id"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.lots.values(), request.args, filters, serialize_lot)


@bp.route("/carpetloop/feedstock-lots/<lot_id>/qc", methods=["POST"])
def qc_lot(lot_id):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    lot = STORE.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404, "Feedstock lot does not exist")
    # Priority 5: QC decisions exist only from RECEIVED.
    if lot["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Lot is not in RECEIVED")
    body = get_body()
    # Priority 11: outcome enum.
    outcome = req_enum(body, "outcome", QC_OUTCOMES)
    lot["status"] = "QC_PASSED" if outcome == "PASS" else "QC_FAILED"
    touch(STORE, lot)
    return success(serialize_lot(lot), 200)


def _resolve_lot_and_batch(lot_id, body):
    """Priority 4, left-to-right: path lot first, then body batch FK."""
    lot = STORE.lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404, "Feedstock lot does not exist")
    batch = None
    batch_id = body.get("batch_id")
    if batch_id is not None:
        batch = STORE.batches.get(batch_id)
        if batch is None:
            raise ApiError("ERR_BATCH_NOT_FOUND", 404, "Batch does not exist")
    return lot, batch


@bp.route("/carpetloop/feedstock-lots/<lot_id>/allocate", methods=["POST"])
def allocate_lot(lot_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    body = get_body()
    lot, batch = _resolve_lot_and_batch(lot_id, body)
    # Priority 5: the mix may only be mutated while the batch is QUARANTINE.
    if batch is not None and batch["status"] != "QUARANTINE":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch has left QUARANTINE")
    # Priority 9: allocation requires the lot to be QC_PASSED.
    if lot["status"] != "QC_PASSED":
        raise ApiError("ERR_LOT_NOT_QC_PASSED", 422, "Lot is not in QC_PASSED")
    # Priority 11: request shape.
    req_str(body, "batch_id")
    quantity = req_decimal(body, "quantity_kg", min_exclusive=0)
    # Priority 12: capacity within the lot's available kilograms.
    if quantity > lot["available_kg"]:
        raise ApiError(
            "ERR_INSUFFICIENT_LOT_KG", 422, "quantity_kg exceeds the lot's available_kg"
        )
    lot["allocated_kg"] += quantity
    lot["available_kg"] -= quantity
    if lot["available_kg"] == 0:
        lot["status"] = "DEPLETED"
    touch(STORE, lot)
    _mix_add(batch, lot["id"], quantity)
    recompute_batch(STORE, batch)
    touch(STORE, batch)
    return success(serialize_lot(lot), 200)


@bp.route("/carpetloop/feedstock-lots/<lot_id>/deallocate", methods=["POST"])
def deallocate_lot(lot_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    body = get_body()
    lot, batch = _resolve_lot_and_batch(lot_id, body)
    # Priority 5: the mix may only be mutated while the batch is QUARANTINE.
    if batch is not None and batch["status"] != "QUARANTINE":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch has left QUARANTINE")
    # Priority 11: request shape. Deallocation is the exact mirror and
    # compensating action of allocation: the quantity may not exceed this
    # lot's entry in the batch's mix (no entry exists -> nothing to release).
    req_str(body, "batch_id")
    quantity = req_decimal(body, "quantity_kg", min_exclusive=0)
    entry = _mix_entry(batch, lot["id"])
    if entry is None or entry["quantity_kg"] < quantity:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "quantity_kg exceeds this lot's allocation in the batch mix",
        )
    entry["quantity_kg"] -= quantity
    if entry["quantity_kg"] == 0:
        batch["feedstock_mix"].remove(entry)
    lot["allocated_kg"] -= quantity
    lot["available_kg"] += quantity
    if lot["status"] == "DEPLETED" and lot["available_kg"] > 0:
        lot["status"] = "QC_PASSED"
    touch(STORE, lot)
    recompute_batch(STORE, batch)
    touch(STORE, batch)
    return success(serialize_lot(lot), 200)


def _mix_entry(batch, lot_id):
    for e in batch["feedstock_mix"]:
        if e["lot_id"] == lot_id:
            return e
    return None


def _mix_add(batch, lot_id, quantity):
    entry = _mix_entry(batch, lot_id)
    if entry is None:
        batch["feedstock_mix"].append({"lot_id": lot_id, "quantity_kg": quantity})
    else:
        entry["quantity_kg"] += quantity
