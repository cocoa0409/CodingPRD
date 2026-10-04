"""FinishedBatch reads, shipping gate, and manual quality hold (PRD 3.6).

Ship gates (in pipeline order): commercial CREATED (ERR_INVALID_STATE) ->
quality CLEAR and no covering INITIATED recall (ERR_BATCH_NOT_SHIPPABLE) ->
>= 75.0% shelf life remaining (ERR_SHELF_LIFE_INSUFFICIENT; the duration is
floored to whole days, so exactly 405 days remaining passes).
"""
from decimal import Decimal

from flask import Blueprint, request

from errors import ApiError
from helpers import (F, filter_enum, invalid_state, new_entity, not_found,
                     paged, pub, require_roles, respond, touch, validate_body)
from services.recall import batch_covered_by_initiated_recall
from state import DB

bp = Blueprint("batches", __name__)

BATCH_READ_ROLES = ("QualityManager", "RecallCoordinator", "SupplyPlanner",
                    "ProductionScheduler")
COMMERCIAL_STATUSES = ["CREATED", "SHIPPED"]
QUALITY_STATUSES = ["CLEAR", "QUALITY_HOLD", "RECALLED", "WITHDRAWN"]
SHELF_LIFE_DAYS = 540
MIN_SHIP_REMAINING_SHELF_LIFE_PCT = Decimal("75.0")


@bp.get("/spice/batches/<batch_id>")
@require_roles(*BATCH_READ_ROLES)
def get_batch(batch_id):
    batch = DB.batches.get(batch_id)
    if batch is None:
        not_found("batch not found")
    return respond(pub(batch))


@bp.get("/spice/batches")
@require_roles(*BATCH_READ_ROLES)
def list_batches():
    production_run_id = request.args.get("production_run_id")
    product_code = request.args.get("product_code")
    commercial_status = filter_enum("commercial_status", COMMERCIAL_STATUSES)
    quality_status = filter_enum("quality_status", QUALITY_STATUSES)
    items = []
    for b in DB.batches.values():
        if production_run_id is not None and b["production_run_id"] != production_run_id:
            continue
        if product_code is not None and b["product_code"] != product_code:
            continue
        if commercial_status is not None and b["commercial_status"] != commercial_status:
            continue
        if quality_status is not None and b["quality_status"] != quality_status:
            continue
        items.append(b)
    data, meta = paged(items)
    return respond(data, page=meta)


@bp.post("/spice/batches/<batch_id>/ship")
@require_roles("SupplyPlanner")
def ship_batch(batch_id):
    batch = DB.batches.get(batch_id)
    if batch is None:
        not_found("batch not found")
    if batch["commercial_status"] != "CREATED":
        invalid_state("Only a batch with commercial_status CREATED can ship")
    if (batch["quality_status"] != "CLEAR"
            or batch_covered_by_initiated_recall(batch_id)):
        raise ApiError("ERR_BATCH_NOT_SHIPPABLE", 409,
                       "Batch is not CLEAR or is covered by an INITIATED recall")
    remaining_days = (batch["best_by_date"] - DB.clock).days  # whole-day floor
    remaining_pct = Decimal(remaining_days) / Decimal(SHELF_LIFE_DAYS) * Decimal(100)
    if remaining_pct < MIN_SHIP_REMAINING_SHELF_LIFE_PCT:
        raise ApiError("ERR_SHELF_LIFE_INSUFFICIENT", 409,
                       "Less than 75.0% of shelf life remains")
    batch["commercial_status"] = "SHIPPED"
    touch(batch)
    return respond(pub(batch))


@bp.post("/spice/batches/<batch_id>/hold")
@require_roles("QualityManager")
def hold_batch(batch_id):
    validate_body({"note": F("str", nullable=True, default=None)})
    batch = DB.batches.get(batch_id)
    if batch is None:
        not_found("batch not found")
    if batch["quality_status"] != "CLEAR":
        invalid_state("Only a CLEAR batch can be placed on hold")
    batch["quality_status"] = "QUALITY_HOLD"
    batch["quality_hold_cause"] = "MANUAL"
    batch["quality_hold_lot_id"] = None
    touch(batch)
    return respond(pub(batch))
