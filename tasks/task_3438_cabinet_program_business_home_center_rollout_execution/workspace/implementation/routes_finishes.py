"""FinishBatch endpoints (PRD 3.4)."""
from flask import Blueprint

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok
from errors import api_error
from util import parse_dt

bp = Blueprint("finishes", __name__)


def serialize(batch):
    return dict(batch)


@bp.route("/cabinet/finish-batches", methods=["POST"])
def create_batch():
    require_roles("PlatformAdmin")
    body = get_body()
    finish_code = body.get("finish_code")
    batch_code = body.get("batch_code")
    lab_l = body.get("lab_l")
    lab_a = body.get("lab_a")
    lab_b = body.get("lab_b")
    effective_from = body.get("effective_from")
    if not isinstance(finish_code, str) or not finish_code:
        raise api_error("ERR_INVALID_REQUEST", "finish_code is required")
    if not isinstance(batch_code, str) or not batch_code:
        raise api_error("ERR_INVALID_REQUEST", "batch_code is required")
    for name, value in (("lab_l", lab_l), ("lab_a", lab_a), ("lab_b", lab_b)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise api_error("ERR_INVALID_REQUEST", name + " must be a number")
    if effective_from is None or parse_dt(effective_from) is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "effective_from must be an ISO 8601 datetime")
    # Registering a batch auto-retires the prior CURRENT batch of the same code.
    for prior in store.batches.values():
        if prior["finish_code"] == finish_code and prior["status"] == "CURRENT":
            prior["status"] = "RETIRED"
            bump(prior)
    batch = new_entity()
    batch.update({
        "finish_code": finish_code,
        "batch_code": batch_code,
        "lab_l": lab_l,
        "lab_a": lab_a,
        "lab_b": lab_b,
        "effective_from": effective_from,
        "status": "CURRENT",
    })
    store.batches[batch["id"]] = batch
    return ok(serialize(batch), 201)


@bp.route("/cabinet/finish-batches/<batch_id>/retire", methods=["POST"])
def retire_batch(batch_id):
    require_roles("PlatformAdmin")
    batch = store.batches.get(batch_id)
    if batch is None:
        raise api_error("ERR_NOT_FOUND", "finish batch not found")
    if batch["status"] != "CURRENT":
        raise api_error("ERR_INVALID_STATE", "only a CURRENT batch can be retired")
    batch["status"] = "RETIRED"
    bump(batch)
    return ok(serialize(batch))
