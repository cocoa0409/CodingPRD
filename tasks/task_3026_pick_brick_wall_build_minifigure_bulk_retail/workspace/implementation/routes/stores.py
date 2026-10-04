"""Store opening, reading, the logical clock and the epoch checkpoint."""

from flask import Blueprint

from db import db, format_iso, parse_iso
from errors import fail
from middleware import require
from response import envelope
from services.core import new_record, recompute_store
from services.epoch import run_epoch
from utils import body, out, require_fields

bp = Blueprint("stores", __name__)


def serialise_store(store):
    return out(store)


def _recompute(store):
    recompute_store(store)
    return store


@bp.route("/stores", methods=["POST"])
def open_store():
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "store_code", "display_name")

    code = payload["store_code"]
    for existing in db().stores.values():
        if existing["store_code"] == code and existing["stage"] != "CLOSED":
            fail("ERR_CONSTRAINT_VIOLATION",
                 "A store code must be unique across non-closed stores.")

    store = new_record({
        "store_code": code,
        "display_name": payload["display_name"],
        "wall_bin_capacity_grams": int(payload.get("wall_bin_capacity_grams", 20000)),
        "bin_engine_mass_grams": 0,
        "shrinkage_basis_points": 0,
        "event_capacity_units": int(payload.get("event_capacity_units", 40)),
        "checklist_required": bool(payload.get("checklist_required", True)),
        "last_event_run_index": 0,
        "stage": "TRADING",
    })
    db().stores[store["id"]] = store
    return envelope(serialise_store(store), status=201)


@bp.route("/stores/<store_id>", methods=["GET"])
def read_store(store_id):
    require("PlatformAdmin", "StoreAssociate", "Member")
    store = db().stores.get(store_id)
    if store is None:
        fail("ERR_NOT_FOUND", "No store exists with id %s." % store_id)
    _recompute(store)
    return envelope(serialise_store(store))


@bp.route("/stores/<store_id>/run_epoch", methods=["POST"])
def run_store_epoch(store_id):
    require("PlatformAdmin")
    store = db().stores.get(store_id)
    if store is None:
        fail("ERR_NOT_FOUND", "No store exists with id %s." % store_id)
    run_epoch(store)
    return envelope(serialise_store(store))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("PlatformAdmin")
    payload = body()
    if payload.get("to_iso8601") in (None, ""):
        fail("ERR_CONSTRAINT_VIOLATION", "to_iso8601 is required.")
    db().clock = parse_iso(payload["to_iso8601"])
    return envelope({"current_utc": format_iso(db().clock)})