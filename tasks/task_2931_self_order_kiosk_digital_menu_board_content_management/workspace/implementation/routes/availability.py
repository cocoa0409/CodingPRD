"""Store inventory, the 86 list and the availability rollup (PRD 3.6)."""
from flask import Blueprint

import auth
import derive
import logical_clock as clockmod
import response
import serialize
import shapes
from db import DB, append_audit, new_row
from errors import fail
from routes.common import fk, listing, path_row

bp = Blueprint("availability", __name__)

VERBS = ("SYNC_ON_HAND", "EIGHTY_SIX", "RESTORE", "DISCONTINUE")


@bp.post("/stores/<store_id>/item-availabilities")
def attach_item(store_id):
    ctx = auth.enter(["PlatformAdmin", "StoreOperator"])
    auth.require_store_scope(ctx, store_id)
    path_row("stores", store_id)
    data = shapes.body()
    item_id = fk(data, "menu_item_id", "menu_items")
    if item_id is None:
        shapes.req_str(data, "menu_item_id", 1, None)
    on_hand = shapes.req_int(data, "on_hand_units", 0, 100000)
    reserved = shapes.opt_int(data, "reserved_units", 0, 100000, 0)
    par = shapes.req_int(data, "par_units", 1, 100000)
    for row in DB.availabilities.values():
        if row.get("store_id") == store_id and row.get("menu_item_id") == item_id:
            fail("ERR_DUPLICATE_AVAILABILITY", "this store already tracks this item")
    row = new_row({
        "store_id": store_id,
        "menu_item_id": item_id,
        "on_hand_units": on_hand,
        "reserved_units": reserved,
        "par_units": par,
        "available_units": 0,
        "supply_state": "IN_STOCK",
        "listing_state": "LISTED",
        "eighty_six_state": "NONE",
        "eighty_six_until_utc": None,
        "eighty_six_reason": None,
        "availability_state": "AVAILABLE",
        "last_sync_utc": clockmod.now_iso(),
    })
    DB.availabilities[row["id"]] = row
    derive.recompute_availability(row, bump=False)
    item = DB.menu_items.get(item_id)
    if item is not None:
        derive.recompute_item(item)
    derive.reconcile()
    return response.created(serialize.dump("availability", row))


@bp.get("/item-availabilities")
def list_availabilities():
    auth.enter(auth.ALL_READ_ROLES)
    return listing("availabilities", "availability")


@bp.get("/item-availabilities/<availability_id>")
def get_availability(availability_id):
    ctx = auth.enter(auth.ALL_READ_ROLES)
    row = DB.availabilities.get(availability_id)
    if row is not None:
        auth.require_store_scope(ctx, row.get("store_id"))
    row = path_row("availabilities", availability_id)
    if not derive.release_auto_hold(row):
        derive.recompute_availability(row)
    return response.ok(serialize.dump("availability", row))


@bp.post("/item-availabilities/<availability_id>/actions")
def drive_availability(availability_id):
    ctx = auth.enter(["PlatformAdmin", "StoreOperator"])
    row = DB.availabilities.get(availability_id)
    if row is not None:
        auth.require_store_scope(ctx, row.get("store_id"))
    row = path_row("availabilities", availability_id)
    data = shapes.body()
    action = shapes.req_enum(data, "action", VERBS)
    if row.get("listing_state") == "DISCONTINUED":
        fail("ERR_ALREADY_TERMINAL", "a discontinued row is terminal")
    item = DB.menu_items.get(row.get("menu_item_id"))

    if action == "SYNC_ON_HAND":
        on_hand = shapes.req_int(data, "on_hand_units", 0, 100000)
        reserved = shapes.opt_int(data, "reserved_units", 0, 100000, row.get("reserved_units", 0))
        derive.apply_changes(row, {
            "on_hand_units": on_hand,
            "reserved_units": reserved,
            "last_sync_utc": clockmod.now_iso(),
        })
        derive.recompute_availability(row)
        if row["available_units"] <= 0 and row.get("listing_state") == "LISTED":
            derive.auto_eighty_six(row, ctx["role"], ctx["user_id"])
        else:
            derive.availability_cascade(row)

    elif action == "EIGHTY_SIX":
        until = shapes.opt_instant(data, "until_utc", None)
        reason = shapes.opt_str(data, "eighty_six_reason", 1, 280, None)
        if row.get("listing_state") != "LISTED":
            fail("ERR_INVALID_STATE_TRANSITION", "EIGHTY_SIX requires a LISTED row")
        derive.apply_changes(row, {
            "listing_state": "EIGHTY_SIXED",
            "eighty_six_state": "MANUAL_86",
            "eighty_six_until_utc": clockmod.iso(until) if until is not None else None,
            "eighty_six_reason": reason,
        })
        derive.recompute_availability(row)
        append_audit("ITEM_AVAILABILITY", row["id"], "ITEM_EIGHTY_SIXED", ctx["role"],
                     ctx["user_id"], detail=reason)
        derive.availability_cascade(row)

    elif action == "RESTORE":
        if row.get("listing_state") != "EIGHTY_SIXED":
            fail("ERR_INVALID_STATE_TRANSITION", "RESTORE requires an EIGHTY_SIXED row")
        derive.apply_changes(row, {
            "listing_state": "LISTED",
            "eighty_six_state": "NONE",
            "eighty_six_until_utc": None,
            "eighty_six_reason": None,
        })
        derive.recompute_availability(row)
        append_audit("ITEM_AVAILABILITY", row["id"], "ITEM_RESTORED", ctx["role"],
                     ctx["user_id"], detail="LISTING_RESTORED")
        derive.availability_cascade(row)

    else:  # DISCONTINUE
        if row.get("listing_state") not in ("LISTED", "EIGHTY_SIXED"):
            fail("ERR_INVALID_STATE_TRANSITION", "DISCONTINUE is not declared out of this state")
        derive.apply_changes(row, {
            "listing_state": "DISCONTINUED",
            "eighty_six_state": "NONE",
        })
        derive.recompute_availability(row)
        append_audit("ITEM_AVAILABILITY", row["id"], "ITEM_DISCONTINUED", ctx["role"],
                     ctx["user_id"], detail="LISTING_DISCONTINUED")
        derive.availability_cascade(row)

    return response.ok(serialize.dump("availability", row))
