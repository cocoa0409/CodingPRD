"""Catalogue, fitment, interchange, supersession, stores and stock
(PRD 3.2)."""

import db
from errors import ApiError, bad_request
from middleware import optional, require_fields, string_field
from services import calc, common

DRIVE_TYPES = ("FWD", "RWD", "AWD", "FOUR_WD")
FITMENT_DRIVE_TYPES = DRIVE_TYPES + ("ANY",)
STORE_TYPES = ("SATELLITE", "HUB", "MEGA_HUB", "DC")
PLACEMENTS = ("FRONT", "REAR_LEFT", "REAR_RIGHT", "OTHER")


def _int(body, field, default=None, required=False):
    if field not in body or body.get(field) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return int(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def _number(body, field, default=None, required=False):
    if field not in body or body.get(field) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    try:
        return float(body[field])
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number." % field)


def _bool(body, field, default=False):
    value = body.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------

def create_part(body):
    require_fields(body, ["sku", "description", "line_code", "list_price_cents"])
    superseded_by = body.get("superseded_by_part_id")
    if superseded_by is not None:
        if db.parts.get(str(superseded_by)) is None:
            raise ApiError("ERR_SUPERSEDING_PART_NOT_FOUND")
        superseded_by = str(superseded_by)
    part = common.new_resource({
        "sku": string_field(body, "sku", required=True),
        "description": string_field(body, "description", required=True),
        "line_code": string_field(body, "line_code", required=True),
        "list_price_cents": _int(body, "list_price_cents", required=True),
        "core_charge_cents": _int(body, "core_charge_cents", default=0),
        "is_hazardous": _bool(body, "is_hazardous", False),
        "is_returnable": _bool(body, "is_returnable", True),
        "is_archived": False,
        "catalog_state": "ACTIVE",
        "superseded_by_part_id": superseded_by,
        "supersession_depth": 0,
    })
    db.parts[part["id"]] = part
    if superseded_by is not None:
        part["catalog_state"] = "SUPERSEDED"
        common.recompute_depths()
    part["supersession_depth"] = common.supersession_depth(part["id"])
    common.remember("parts", part["id"])
    return part


def supersede_part(part, body):
    require_fields(body, ["superseding_part_id"])
    target_id = str(body["superseding_part_id"])
    if part.get("catalog_state") != "ACTIVE":
        raise ApiError("ERR_PART_ALREADY_SUPERSEDED")
    target = db.parts.get(target_id)
    if target is None or target.get("is_archived"):
        raise ApiError("ERR_SUPERSEDING_PART_NOT_FOUND")
    if target.get("superseded_by_part_id") is not None:
        raise ApiError("ERR_SUPERSEDING_PART_NOT_TERMINAL")
    if target["id"] in common.chain_parts(part["id"]) or target["id"] == part["id"]:
        raise ApiError("ERR_SUPERSESSION_CYCLE")

    part["superseded_by_part_id"] = target["id"]
    part["catalog_state"] = "SUPERSEDED"
    common.recompute_depths()
    common.record_audit(part)
    return part


def unsupersede_part(part, body=None):
    if part.get("catalog_state") != "SUPERSEDED":
        raise ApiError("ERR_PART_NOT_SUPERSEDED")
    part["superseded_by_part_id"] = None
    part["catalog_state"] = "ACTIVE"
    common.recompute_depths()
    part["supersession_depth"] = 0
    common.record_audit(part)
    return part


def archive_part(part, body=None):
    common.archive_guard("Part", part)
    part["is_archived"] = True
    common.record_audit(part)
    return part


def add_part_fitment(part, body):
    require_fields(body, ["year_from", "year_to", "make", "model"])
    year_from = _int(body, "year_from", required=True)
    year_to = _int(body, "year_to", required=True)
    drive_type = string_field(body, "drive_type", default="ANY")
    if drive_type not in FITMENT_DRIVE_TYPES:
        bad_request("drive_type must be FWD, RWD, AWD, FOUR_WD or ANY.")
    if year_to < year_from:
        raise ApiError("ERR_FITMENT_YEAR_RANGE_INVALID")
    fitment = common.slim_resource({
        "part_id": part["id"],
        "year_from": year_from,
        "year_to": year_to,
        "make": string_field(body, "make", required=True),
        "model": string_field(body, "model", required=True),
        "engine_code": string_field(body, "engine_code", default="ANY"),
        "drive_type": drive_type,
    })
    db.part_fitments[fitment["id"]] = fitment
    common.remember("part_fitments", fitment["id"])
    return fitment


def add_interchange(part, body):
    require_fields(body, ["interchange_sku", "interchange_brand"])
    row = common.slim_resource({
        "part_id": part["id"],
        "interchange_sku": string_field(body, "interchange_sku", required=True),
        "interchange_brand": string_field(body, "interchange_brand", required=True),
    })
    db.part_interchanges[row["id"]] = row
    common.remember("part_interchanges", row["id"])
    return row


def resolve_current_part(queried_part_id):
    part = db.parts.get(queried_part_id)
    if part is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    terminal = common.resolve_current(queried_part_id)
    if terminal is None:
        terminal = part
    return {
        "queried_part_id": queried_part_id,
        "current_part_id": terminal["id"],
        "current_sku": terminal.get("sku"),
        "supersession_depth": common.supersession_depth(queried_part_id),
    }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def create_store(body):
    require_fields(body, ["store_code", "name", "store_type", "delivery_radius_miles",
                          "promise_time_minutes", "daily_capacity_units"])
    store_type = string_field(body, "store_type", required=True)
    if store_type not in STORE_TYPES:
        bad_request("store_type must be SATELLITE, HUB, MEGA_HUB or DC.")
    hub_store_id = optional(body, "hub_store_id")
    if hub_store_id is not None:
        if db.stores.get(str(hub_store_id)) is None:
            raise ApiError("ERR_STORE_NOT_FOUND")
        hub_store_id = str(hub_store_id)
    store = common.new_resource({
        "store_code": string_field(body, "store_code", required=True),
        "name": string_field(body, "name", required=True),
        "store_type": store_type,
        "hub_store_id": hub_store_id,
        "delivery_radius_miles": _number(body, "delivery_radius_miles", required=True),
        "cutoff_hour_local": _int(body, "cutoff_hour_local", default=15),
        "cutoff_buffer_minutes": _int(body, "cutoff_buffer_minutes", default=30),
        "promise_time_minutes": _int(body, "promise_time_minutes", required=True),
        "daily_capacity_units": _int(body, "daily_capacity_units", required=True),
        "committed_units_today": 0,
        "capacity_epoch_at": calc._fmt(db.clock()),
        "is_archived": False,
    })
    db.stores[store["id"]] = store
    common.remember("stores", store["id"])
    return store


def archive_store(store, body=None):
    common.archive_guard("Store", store)
    store["is_archived"] = True
    common.record_audit(store)
    return store


def advance_epoch(to_instant):
    """Reset committed_units_today for every store whose capacity_epoch_at is
    at least 24 hours behind the requested instant (PRD 3.9)."""
    advanced = []
    reset_total = 0
    for store in db.stores.values():
        epoch = calc._parse(store.get("capacity_epoch_at"))
        if epoch is None:
            continue
        if (to_instant - epoch).total_seconds() >= 86400:
            reset_total += store.get("committed_units_today") or 0
            store["committed_units_today"] = 0
            store["capacity_epoch_at"] = calc._fmt(to_instant)
            common.record_audit(store)
            advanced.append(store["id"])
    return advanced, reset_total


# ---------------------------------------------------------------------------
# InventoryItem
# ---------------------------------------------------------------------------

def create_inventory_item(body):
    require_fields(body, ["store_id", "part_id", "on_hand_units"])
    store = db.stores.get(str(body["store_id"]))
    if store is None:
        raise ApiError("ERR_STORE_NOT_FOUND")
    part = db.parts.get(str(body["part_id"]))
    if part is None:
        raise ApiError("ERR_PART_NOT_FOUND")
    item = common.inventory_item_for(store["id"], part["id"])
    if item is None:
        item = common.new_resource({
            "store_id": store["id"],
            "part_id": part["id"],
            "on_hand_units": _int(body, "on_hand_units", required=True),
            "reserved_units": 0,
        })
        db.inventory_items[item["id"]] = item
    else:
        item["on_hand_units"] = (item.get("on_hand_units") or 0) + _int(body, "on_hand_units")
        common.record_audit(item)
    common.remember("inventory_items", item["id"])
    return item


def update_inventory_item(item, body):
    require_fields(body, ["on_hand_units"])
    item["on_hand_units"] = _int(body, "on_hand_units", required=True)
    if item["on_hand_units"] < 0:
        bad_request("on_hand_units must not be negative.")
    common.record_audit(item)
    return item




