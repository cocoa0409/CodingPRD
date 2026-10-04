"""ProductCollection and TileBatch endpoints (PRD 3.1, 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

from auth import authenticate, authorize
from calcs import recompute_batch
from constants import (
    ALL_ROLES,
    BACKING_TYPES,
    BOUNDARIES,
    CLAIM_INTENTS,
    TILE_MASS_KG_PER_M2,
)
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_batch, serialize_collection
from store import STORE, new_common, touch
from util import get_body, opt_enum, q2, q3, req_decimal, req_dt, req_enum, req_str

bp = Blueprint("collections", __name__)


@bp.route("/carpetloop/collections", methods=["POST"])
def create_collection():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    # Priority 11: request shape.
    name = req_str(body, "name")
    pattern_code = req_str(body, "pattern_code")
    backing_type = req_enum(body, "backing_type", BACKING_TYPES)
    boundary = req_enum(body, "lifecycle_boundary", BOUNDARIES)
    claim_intent = opt_enum(body, "claim_intent", CLAIM_INTENTS, "NONE")
    c = new_common(STORE)
    c.update(
        {
            "name": name,
            "pattern_code": pattern_code,
            "backing_type": backing_type,
            "lifecycle_boundary": boundary,
            "claim_intent": claim_intent,
            "status": "ACTIVE",
        }
    )
    STORE.collections[c["id"]] = c
    return success(serialize_collection(c), 201)


@bp.route("/carpetloop/collections/<collection_id>", methods=["GET"])
def get_collection(collection_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = STORE.collections.get(collection_id)
    if c is None:
        raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    return success(serialize_collection(c), 200)


@bp.route("/carpetloop/collections/<collection_id>/sunset", methods=["POST"])
def sunset_collection(collection_id):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    c = STORE.collections.get(collection_id)
    if c is None:
        raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    # Priority 5: transition existence.
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Collection is not ACTIVE")
    c["status"] = "SUNSET"
    touch(STORE, c)
    return success(serialize_collection(c), 200)


@bp.route("/carpetloop/collections/<collection_id>/batches", methods=["POST"])
def create_batch(collection_id):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    # Priority 4: path id existence.
    c = STORE.collections.get(collection_id)
    if c is None:
        raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    # Priority 6: batch creation requires an ACTIVE collection.
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_COLLECTION_SUNSET", 409, "Collection is SUNSET")
    body = get_body()
    # Priority 11: request shape, then dye-lot uniqueness.
    dye_lot_code = req_str(body, "dye_lot_code")
    production_date = req_dt(body, "production_date")
    produced_m2 = req_decimal(body, "produced_m2", min_exclusive=0)
    mfg_intensity = req_decimal(body, "mfg_intensity_kgco2e_per_m2", min_exclusive=0)
    delta_e = req_decimal(body, "delta_e", min_inclusive=0)
    for b in STORE.batches.values():
        if b["collection_id"] == collection_id and b["dye_lot_code"] == dye_lot_code:
            raise ApiError(
                "ERR_DYE_LOT_CONFLICT", 409, "dye_lot_code already exists in this collection"
            )
    b = new_common(STORE)
    b.update(
        {
            "collection_id": collection_id,
            "dye_lot_code": dye_lot_code,
            "production_date": production_date,
            "produced_m2": produced_m2,
            "mfg_intensity_kgco2e_per_m2": mfg_intensity,
            "delta_e": delta_e,
            "feedstock_mix": [],
            "allocated_mass_kg": Decimal("0"),
            "available_m2": produced_m2,
            # recycled_content_pct is undefined (null) while the mix is empty;
            # the embodied-carbon formula is defined for an empty mix
            # (feedstock component 0), so it is stored from creation.
            "recycled_content_pct": None,
            "embodied_carbon_kg_per_m2": q3(mfg_intensity),
            "status": "QUARANTINE",
        }
    )
    STORE.batches[b["id"]] = b
    return success(serialize_batch(b), 201)


@bp.route("/carpetloop/batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    b = STORE.batches.get(batch_id)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404, "Batch does not exist")
    return success(serialize_batch(b), 200)


@bp.route("/carpetloop/batches", methods=["GET"])
def list_batches():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("collection_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.batches.values(), request.args, filters, serialize_batch)


@bp.route("/carpetloop/batches/<batch_id>/release", methods=["POST"])
def release_batch(batch_id):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = STORE.batches.get(batch_id)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404, "Batch does not exist")
    # Priority 5: transition existence.
    if b["status"] != "QUARANTINE":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch is not in QUARANTINE")
    # Priority 6: release requires an ACTIVE collection.
    c = STORE.collections.get(b["collection_id"])
    if c is not None and c["status"] != "ACTIVE":
        raise ApiError("ERR_COLLECTION_SUNSET", 409, "Collection is SUNSET")
    # Priority 11: mass balance at 2 decimal places.
    required = q2(b["produced_m2"] * TILE_MASS_KG_PER_M2)
    if q2(b["allocated_mass_kg"]) != required:
        raise ApiError(
            "ERR_MIX_MASS_MISMATCH",
            422,
            "allocated_mass_kg must equal produced_m2 x 4.0 at 2 decimal places",
        )
    # Re-validate both computed fields one final time at release.
    recompute_batch(STORE, b)
    b["status"] = "RELEASED"
    touch(STORE, b)
    return success(serialize_batch(b), 200)
