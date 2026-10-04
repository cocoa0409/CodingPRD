"""ProductionBatch, AllocationUnit and DeliveryEstimate routes."""

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import body, instant_field, counted, int_field, paged, text_field
from services import order_flow

bp = Blueprint("production", __name__)


@bp.post("/production-batches")
def create_batch():
    from services import sales
    payload = body()
    batch = sales.create_batch(
        text_field(payload, "factory_code"),
        text_field(payload, "model_code"),
        int_field(payload, "unit_capacity", 0),
        instant_field(payload, "planned_completion_at"),
    )
    return object_response(serialize(batch), 201)


@bp.get("/production-batches")
def list_batches():
    rows = [r for r in DB.batches.values()
            if matches(request.args, "model_code", r["model_code"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/production-batches/<batch_id>")
def get_batch(batch_id):
    return object_response(serialize(get("batch", batch_id)))


@bp.post("/production-batches/<batch_id>/start")
def start_batch(batch_id):
    from services import sales
    return object_response(serialize(sales.start_batch(get("batch", batch_id))))


@bp.post("/production-batches/<batch_id>/delay")
def delay_batch(batch_id):
    batch = get("batch", batch_id)
    payload = body()
    if batch["status"] not in ("IN_PRODUCTION", "DELAYED"):
        fail("ERR_BATCH_NOT_DELAYABLE")
    delay_days = int_field(payload, "delay_days", 0)
    if delay_days < 1:
        fail("ERR_INVALID_DELAY_DAYS")
    return object_response(serialize(order_flow.delay_batch(batch, delay_days)))


@bp.post("/production-batches/<batch_id>/resume")
def resume_batch(batch_id):
    from services import sales
    return object_response(serialize(sales.resume_batch(get("batch", batch_id))))


@bp.post("/production-batches/<batch_id>/complete")
def complete_batch(batch_id):
    from services import sales
    return object_response(serialize(sales.complete_batch(get("batch", batch_id))))


@bp.post("/production-batches/<batch_id>/allocation-units")
def mint_unit(batch_id):
    from services import sales
    batch = get("batch", batch_id)
    payload = body()
    unit = sales.mint_unit(batch, text_field(payload, "vin"))
    return object_response(serialize(unit), 201)


@bp.get("/production-batches/<batch_id>/allocation-units")
def list_batch_units(batch_id):
    batch = get("batch", batch_id)
    rows = [r for r in DB.units.values()
            if r["batch_id"] == batch["id"]
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/allocation-units/<unit_id>")
def get_unit(unit_id):
    return object_response(serialize(get("unit", unit_id)))


@bp.get("/delivery-estimates")
def list_estimates():
    rows = [r for r in DB.estimates.values()
            if matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "estimate_state", r["estimate_state"])
            and matches(request.args, "notification_state", r["notification_state"])]
    prior = request.args.get("prior_estimate_id")
    if prior not in (None, ""):
        rows = [r for r in rows if str(r["prior_estimate_id"]) == str(prior)]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/delivery-estimates/<estimate_id>")
def get_estimate(estimate_id):
    return object_response(serialize(get("estimate", estimate_id)))


@bp.post("/delivery-estimates/<estimate_id>/restore")
def restore_estimate(estimate_id):
    estimate = get("estimate", estimate_id)
    return object_response(serialize(order_flow.restore_estimate(estimate)))