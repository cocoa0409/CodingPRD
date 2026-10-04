from flask import Blueprint, request
from db import STORE, new_entity, touch, logical_now
from errors import (ApiError, err_invalid_request, err_invalid_state,
                    ERR_WAVE_WINDOW_OVERLAP, ERR_OUTSIDE_SHIP_WINDOW,
                    ERR_INVALID_ORDER_QUANTITY, ERR_SHORTAGE_PENDING)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, get_pagination, paginate,
                     store_lookup, ser_wave, ser_asset, parse_iso8601, iso_z,
                     iso_z_logical, account_of_wave)
from response import success_object, success_list

bp = Blueprint("waves", __name__)

LIVE_WAVE_STATES = {"PLANNED", "RELEASED", "SHIPPED"}


def _validate_destinations(raw):
    if not isinstance(raw, list):
        raise err_invalid_request("destinations must be an array")
    out = []
    for d in raw:
        if not isinstance(d, dict):
            raise err_invalid_request("destinations entries must be objects")
        emp = d.get("employee_ref")
        addr = d.get("address")
        units = d.get("units")
        if not isinstance(emp, str) or not isinstance(addr, str):
            raise err_invalid_request("destinations entries require employee_ref and address strings")
        if not isinstance(units, int) or isinstance(units, bool):
            raise err_invalid_request("destinations entries require integer units")
        out.append({"employee_ref": emp, "address": addr, "units": units})
    return out


def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


def _check_wave_overlap(order_id, start_dt, end_dt, exclude_id=None):
    for w in STORE.waves.values():
        if w["order_id"] != order_id or w["id"] == exclude_id:
            continue
        if w["status"] not in LIVE_WAVE_STATES:
            continue
        ws = parse_iso8601(w["ship_window_start"])
        we = parse_iso8601(w["ship_window_end"])
        if _windows_overlap(start_dt, end_dt, ws, we):
            raise ApiError(ERR_WAVE_WINDOW_OVERLAP,
                           "Wave window overlaps another live wave of the same order", 422)


def _check_drop_ship_totals(order_id, new_dests):
    """Destination units across a drop-ship line's waves must sum exactly to line qty.
    Evaluated against the order's drop-ship lines using all live waves including the new one."""
    lines = [l for l in STORE.order_lines.values()
             if l["order_id"] == order_id and l["ship_to_mode"] == "DROP_SHIP_EMPLOYEES"]
    if not lines:
        return
    existing = 0
    for w in STORE.waves.values():
        if w["order_id"] == order_id and w["status"] in LIVE_WAVE_STATES:
            existing += sum(d["units"] for d in w["destinations"])
    planned = sum(d["units"] for d in new_dests)
    total_lines_qty = sum(l["qty"] for l in lines)
    if existing + planned > total_lines_qty:
        raise ApiError(ERR_INVALID_ORDER_QUANTITY,
                       "Drop-ship destination units exceed line qty", 422)


@bp.post("/api/orders/<oid>/deployment-waves")
def create_wave(oid):
    require_roles("AccountManager")
    order = store_lookup("orders", oid)
    body = get_json_body()
    label = require_field(body, "wave_label", str)
    start_raw = require_field(body, "ship_window_start", str)
    end_raw = require_field(body, "ship_window_end", str)
    start_dt = parse_iso8601(start_raw, "ship_window_start")
    end_dt = parse_iso8601(end_raw, "ship_window_end")
    if "destinations" not in body:
        raise err_invalid_request("Missing required field: destinations")
    dests = _validate_destinations(body["destinations"])
    _check_wave_overlap(oid, start_dt, end_dt)
    _check_drop_ship_totals(oid, dests)
    ent = new_entity()
    ent.update({
        "order_id": oid,
        "wave_label": label,
        "ship_window_start": iso_z_logical(start_dt),
        "ship_window_end": iso_z_logical(end_dt),
        "destinations": dests,
        "status": "PLANNED",
    })
    STORE.waves[ent["id"]] = ent
    return success_object(ser_wave(ent), 201)


@bp.get("/api/orders/<oid>/deployment-waves")
def list_order_waves(oid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    limit, offset = get_pagination()
    items = [w for w in STORE.waves.values() if w["order_id"] == oid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_wave(w) for w in items], limit, offset, total)


def _order_on_hold_with_pending_sub(order):
    if order["build_status"] != "ON_HOLD":
        return False
    jobs = [j for j in STORE.build_jobs.values()
            if j["order_id"] == order["id"] and j["status"] == "SHORTAGE_BLOCKED"]
    for j in jobs:
        for sr in STORE.sub_requests.values():
            if sr["build_job_id"] == j["id"] and sr["status"] == "PENDING":
                return True
    return False


@bp.post("/api/deployment-waves/<wid>/release")
def release_wave(wid):
    require_roles("AccountManager")
    wave = store_lookup("waves", wid)
    if wave["status"] != "PLANNED":
        raise err_invalid_state("Wave is not PLANNED")
    order = STORE.orders.get(wave["order_id"])
    # priority 5: the ON_HOLD shortage freeze outranks every wave-window and
    # build-state business rule (PRD §3.7, §2.9)
    if order is not None and _order_on_hold_with_pending_sub(order):
        raise ApiError(ERR_SHORTAGE_PENDING,
                       "Order is ON_HOLD with a PENDING substitution", 409)
    if order is None or order["build_status"] != "BUILT":
        raise err_invalid_state("Order build_status is not BUILT")
    start_dt = parse_iso8601(wave["ship_window_start"])
    end_dt = parse_iso8601(wave["ship_window_end"])
    _check_wave_overlap(order["id"], start_dt, end_dt, exclude_id=wave["id"])
    wave["status"] = "RELEASED"
    touch(wave)
    if order["ship_status"] == "PENDING":
        order["ship_status"] = "STAGED"
        touch(order)
    return success_object(ser_wave(wave))


def _covered_assets(wave):
    """Assets covered by the wave's destinations: assets of the order's drop-ship
    lines in insertion order; single-address lines' assets are covered by any wave
    of the order."""
    order_id = wave["order_id"]
    lines = [l for l in STORE.order_lines.values() if l["order_id"] == order_id]
    line_ids = {l["id"] for l in lines}
    assets = [a for a in STORE.assets.values() if a["order_line_id"] in line_ids]
    assets.sort(key=lambda a: (a["created_at"], a["id"]))
    return assets


@bp.post("/api/deployment-waves/<wid>/ship")
def ship_wave(wid):
    require_roles("FactoryOps")
    wave = store_lookup("waves", wid)
    if wave["status"] != "RELEASED":
        raise err_invalid_state("Wave is not RELEASED")
    order = STORE.orders.get(wave["order_id"])
    if order is not None and _order_on_hold_with_pending_sub(order):
        raise ApiError(ERR_SHORTAGE_PENDING,
                       "Order is ON_HOLD with a PENDING substitution", 409)
    now = logical_now()
    start_dt = parse_iso8601(wave["ship_window_start"])
    end_dt = parse_iso8601(wave["ship_window_end"])
    if not (start_dt <= now < end_dt):
        raise ApiError(ERR_OUTSIDE_SHIP_WINDOW,
                       "Current logical clock is outside the wave's ship window", 422)
    wave["status"] = "SHIPPED"
    touch(wave)
    # move covered staged assets to IN_TRANSIT, stamping destinations in order
    dest_iter = []
    for d in wave["destinations"]:
        for _ in range(d["units"]):
            dest_iter.append(d["employee_ref"])
    idx = 0
    for asset in _covered_assets(wave):
        if asset["status"] != "STAGED":
            continue
        asset["status"] = "IN_TRANSIT"
        if idx < len(dest_iter):
            asset["destination_employee_ref"] = dest_iter[idx]
            idx += 1
        touch(asset)
    if order is not None:
        others_live = [w for w in STORE.waves.values()
                       if w["order_id"] == order["id"] and w["id"] != wave["id"]
                       and w["status"] in ("PLANNED", "RELEASED")]
        if order["ship_status"] == "STAGED":
            order["ship_status"] = "PARTIALLY_SHIPPED" if others_live else "SHIPPED"
            touch(order)
        elif order["ship_status"] == "PARTIALLY_SHIPPED" and not others_live:
            order["ship_status"] = "SHIPPED"
            touch(order)
    return success_object(ser_wave(wave))


@bp.post("/api/deployment-waves/<wid>/receive")
def receive_wave(wid):
    uid, role = require_roles("CustomerUser")
    wave = store_lookup("waves", wid)
    require_ownership(account_of_wave(wave), uid, role)
    if wave["status"] != "SHIPPED":
        raise err_invalid_state("Wave is not SHIPPED")
    wave["status"] = "RECEIVED"
    touch(wave)
    order = STORE.orders.get(wave["order_id"])
    for asset in _covered_assets(wave):
        if asset["status"] == "IN_TRANSIT":
            asset["status"] = "DELIVERED"
            touch(asset)
    if order is not None:
        others_inflight = [w for w in STORE.waves.values()
                           if w["order_id"] == order["id"] and w["id"] != wave["id"]
                           and w["status"] in ("RELEASED", "SHIPPED")]
        if not others_inflight and order["ship_status"] in ("PARTIALLY_SHIPPED", "SHIPPED", "STAGED"):
            order["ship_status"] = "DELIVERED"
            touch(order)
            account = STORE.accounts.get(order["account_id"])
            if account is not None:
                account["outstanding_cents"] -= order["total_cents"]
                touch(account)
    return success_object(ser_wave(wave))


@bp.post("/api/deployment-waves/<wid>/cancel")
def cancel_wave(wid):
    require_roles("AccountManager")
    wave = store_lookup("waves", wid)
    if wave["status"] != "PLANNED":
        raise err_invalid_state("Wave is not PLANNED")
    wave["status"] = "CANCELLED"
    touch(wave)
    return success_object(ser_wave(wave))


# ---------------- assets ----------------

@bp.get("/api/order-lines/<lid>/assets")
def list_line_assets(lid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    line = store_lookup("order_lines", lid)
    order = STORE.orders.get(line["order_id"])
    if order:
        require_ownership(order["account_id"], uid, role)
    limit, offset = get_pagination()
    items = [a for a in STORE.assets.values() if a["order_line_id"] == lid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_asset(a) for a in items], limit, offset, total)


@bp.get("/api/assets/<aid>")
def get_asset(aid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    asset = store_lookup("assets", aid)
    line = STORE.order_lines.get(asset["order_line_id"])
    order = STORE.orders.get(line["order_id"]) if line else None
    if order:
        require_ownership(order["account_id"], uid, role)
    return success_object(ser_asset(asset))


@bp.get("/api/assets")
def list_assets():
    require_roles("PlatformAdmin", "AccountManager", "FactoryOps")
    limit, offset = get_pagination()
    items = list(STORE.assets.values())
    for f in ("order_line_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_asset(a) for a in items], limit, offset, total)


@bp.get("/api/orders/<oid>/asset-report")
def asset_report(oid):
    uid, role = require_roles("AccountManager", "CustomerUser", "PlatformAdmin")
    order = store_lookup("orders", oid)
    require_ownership(order["account_id"], uid, role)
    line_ids = {l["id"] for l in STORE.order_lines.values() if l["order_id"] == oid}
    assets = [a for a in STORE.assets.values() if a["order_line_id"] in line_ids]
    assets.sort(key=lambda a: (a["created_at"], a["id"]))
    rows = [{
        "serial_number": a["serial_number"],
        "asset_tag": a["asset_tag"],
        "order_line_id": a["order_line_id"],
        "destination_employee_ref": a["destination_employee_ref"],
        "asset_status": a["status"],
    } for a in assets]
    return success_object({"po_number": order["po_number"], "rows": rows})
