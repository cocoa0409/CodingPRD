"""The wall: bin loading, reading, restock, allocation history and rotation."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import require
from response import envelope, paginate
from services.core import (
    get_bin,
    get_element,
    get_store,
    new_record,
    recompute_store,
    touch,
)
from services.wall import (
    activate_element_if_loaded,
    mutate_bin,
    recompute_bin,
    run_rotation,
)
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("wall_bins", __name__)


@bp.route("/stores/wall-bins", methods=["POST"])
def load_bin():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "element_id", "bin_label", "bin_capacity_grams")

    store = get_store(payload["store_id"])
    element = get_element(payload["element_id"])

    capacity = int(payload["bin_capacity_grams"])
    if capacity <= 0:
        fail("ERR_CONSTRAINT_VIOLATION", "bin_capacity_grams must be greater than zero.")
    mass = int(payload.get("bin_mass_grams", 0))
    if mass < 0:
        fail("ERR_CONSTRAINT_VIOLATION", "bin_mass_grams may not be negative.")
    if mass > capacity:
        fail("ERR_CONSTRAINT_VIOLATION", "bin_mass_grams may not exceed the bin capacity.")

    label = payload["bin_label"]
    for existing in db().wall_bins.values():
        if existing["store_id"] == store["id"] and existing["bin_label"] == label:
            fail("ERR_CONSTRAINT_VIOLATION", "A bin label is unique within a store.")

    bin_record = new_record({
        "store_id": store["id"],
        "element_id": element["id"],
        "bin_label": label,
        "bin_capacity_grams": capacity,
        "bin_mass_grams": mass,
        "fill_pct": 0,
        "depletion_rate_pct_per_day": 0,
        "status": "OPEN",
        "last_restock_index": store["last_event_run_index"],
    })
    recompute_bin(bin_record)
    db().wall_bins[bin_record["id"]] = bin_record

    if mass > 0:
        activate_element_if_loaded(element)
    recompute_store(store)
    touch(store)
    return envelope(out(bin_record), status=201)


@bp.route("/stores/wall-bins", methods=["GET"])
def list_bins():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [b for b in db().wall_bins.values()
             if matches(b, params, "store_id", "element_id", "status")]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/wall-bins/<bin_id>", methods=["GET"])
def read_bin(bin_id):
    require("StoreAssociate", "Member")
    return envelope(out(get_bin(bin_id)))


@bp.route("/stores/wall-bins/<bin_id>/allocations", methods=["GET"])
def bin_allocations(bin_id):
    require("StoreAssociate")
    bin_record = get_bin(bin_id)
    items = [a for a in db().fusion_allocations.values()
             if a["wall_bin_id"] == bin_record["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, pagination = paginate(items, list_params())
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/wall-bins/<bin_id>/restock", methods=["POST"])
def restock_bin(bin_id):
    require("StoreAssociate")
    payload = body()
    bin_record = get_bin(bin_id)

    add_grams = int(payload.get("add_grams") or 0)
    if add_grams <= 0:
        fail("ERR_CONSTRAINT_VIOLATION", "add_grams must be a positive number of grams.")
    if bin_record["bin_mass_grams"] + add_grams > bin_record["bin_capacity_grams"]:
        fail("ERR_CONSTRAINT_VIOLATION",
             "The addition would overfill the bin; an overfill is refused, not clamped.")

    mutate_bin(bin_record, add_grams)
    element = db().elements.get(bin_record["element_id"])
    if element is not None and bin_record["bin_mass_grams"] > 0:
        activate_element_if_loaded(element)
    return envelope(out(bin_record))


@bp.route("/stores/wall-bins/rotate", methods=["POST"])
def rotate_wall():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "bin_ids")
    store = get_store(payload["store_id"])
    restocked = run_rotation(store["id"], payload["bin_ids"] or [])
    return envelope(out(restocked), response_type="array")