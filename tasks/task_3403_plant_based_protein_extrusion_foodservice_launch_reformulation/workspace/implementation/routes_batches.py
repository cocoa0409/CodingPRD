# FinishedGoodsBatch domain (PRD 3.7): read-side derived_status against the
# logical clock, and the FEFO-guarded reservation to programs.
from flask import Blueprint, request

import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import batch_derived_status, serialize_batch
from store import db, flush_dirty, mark
from validation import Shape, body_json, get_int, get_str

bp = Blueprint("batches", __name__, url_prefix="/protein-ops/finished-goods-batches")

ANY_ROLE = constants.ROLES


@bp.route("", methods=["GET"])
def list_batches():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["batches"].values())
    for param in ("production_run_id", "product_id", "reserved_for_program_id", "channel"):
        value = request.args.get(param)
        if value is not None:
            items = [b for b in items if b.get(param) == value]
    derived_filter = request.args.get("derived_status")
    if derived_filter is not None:
        items = [b for b in items if batch_derived_status(b) == derived_filter]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, meta = paginate([serialize_batch(b) for b in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<bid>", methods=["GET"])
def get_batch(bid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    batch = db["batches"].get(bid)
    if batch is None:
        raise err("ERR_NOT_FOUND", "finished goods batch not found")
    return success(serialize_batch(batch), "object", 200)


@bp.route("/<bid>/reserve", methods=["POST"])
def reserve_batch(bid):
    _user_id, role = authenticate()
    authorize(role, ["ChannelManager"])

    batch = db["batches"].get(bid)
    if batch is None:
        raise err("ERR_NOT_FOUND", "finished goods batch not found")

    body = body_json()
    shape = Shape()
    program_id = get_str(body, "program_id", shape)
    quantity_cases = get_int(body, "quantity_cases", shape, minv=1)

    # Tier 3: body FK existence (declared input order — program_id first).
    program = None
    if program_id is not None:
        program = db["programs"].get(program_id)
        if program is None:
            raise err("ERR_NOT_FOUND", "program_id does not reference a program")

    # Tier 5: EXPIRED / WRITTEN_OFF / DEPLETED batches refuse reservation.
    derived = batch_derived_status(batch)
    if derived in ("EXPIRED", "WRITTEN_OFF", "DEPLETED"):
        raise err("ERR_INVALID_STATE", "batch derived_status %s is not reservable" % derived)

    # Tier 8 structural, in sub-order: channel mapping, one-program-per-batch,
    # FEFO, reservation quantity, product match.
    if program is not None:
        if constants.PROGRAM_CHANNEL_MAP[program["program_type"]] != batch["channel"]:
            raise err("ERR_CHANNEL_PROGRAM_MISMATCH", "batch channel does not match the program type mapping")
        if batch["reserved_cases"] > 0 and batch["reserved_for_program_id"] != program["id"]:
            raise err("ERR_BATCH_ALREADY_RESERVED", "batch already reserved to a different program")
        for other in db["batches"].values():
            if other["id"] == batch["id"]:
                continue
            if other["product_id"] != batch["product_id"] or other["channel"] != batch["channel"]:
                continue
            if other["_dt"]["expiry_date"] < batch["_dt"]["expiry_date"] and other["available_cases"] > 0:
                raise err("ERR_FEFO_VIOLATION", "an earlier-expiry batch of the same product and channel has cases available")
        if quantity_cases is not None and quantity_cases > batch["available_cases"]:
            raise err("ERR_INSUFFICIENT_AVAILABLE_CASES", "quantity_cases exceeds available_cases")
        if program["product_id"] != batch["product_id"]:
            raise err("ERR_PRODUCT_MISMATCH", "program product does not match the batch product")

        # Tier 9 cross-entity: program must be accepting volume.
        if program["status"] not in ("ACTIVE", "IN_WINDOW"):
            raise err("ERR_PROGRAM_NOT_ACCEPTING_RUNS", "program status is not ACTIVE or IN_WINDOW")

    shape.raise_if_any()

    batch["available_cases"] -= quantity_cases
    batch["reserved_cases"] += quantity_cases
    batch["reserved_for_program_id"] = program_id
    mark(batch)
    flush_dirty()
    return success(serialize_batch(batch), "object", 200)
