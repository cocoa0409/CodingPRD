"""Capacity pools and reservations."""
from datetime import timedelta

import clock
import util
from db import db
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_CAPACITY_INSUFFICIENT, ERR_HOLD_EXPIRED,
)
from services import calc

SCOPE_KINDS = {"REGION", "EVENT"}


def create_pool(body):
    util.require_fields(body, ["pool_code", "scope_kind", "total_units"],
                        allowed_extra=["region_code", "window_id", "oversubscribe_pct"])
    util.req_str(body["pool_code"], "pool_code")
    util.req_enum(body["scope_kind"], "scope_kind", SCOPE_KINDS)
    total_units = util.req_int(body["total_units"], "total_units", minimum=0)
    oversub = body.get("oversubscribe_pct", 0)
    oversub = util.req_int(oversub, "oversubscribe_pct", minimum=0, maximum=50)
    region_code = body.get("region_code")
    window_id = body.get("window_id")
    if body["scope_kind"] == "REGION":
        if not isinstance(region_code, str) or not region_code:
            raise_err(ERR_INVALID_REQUEST, "region_code required for REGION scope")
        window_id = None
    else:
        if not isinstance(window_id, str) or not window_id:
            raise_err(ERR_INVALID_REQUEST, "window_id required for EVENT scope")
        if window_id not in db.windows:
            raise_err(ERR_NOT_FOUND, "window not found")
        region_code = None
    for p in db.capacity_pools.values():
        if p["pool_code"] == body["pool_code"]:
            raise_err(ERR_INVALID_REQUEST, "pool_code must be unique")
    now_iso = clock.now_iso()
    pool = {
        "id": util.new_id(),
        "pool_code": body["pool_code"],
        "scope_kind": body["scope_kind"],
        "region_code": region_code,
        "window_id": window_id,
        "total_units": total_units,
        "committed_units": 0,
        "oversubscribe_pct": oversub,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.capacity_pools[pool["id"]] = pool
    return pool


def create_reservation(body):
    util.require_fields(body, ["pool_id", "window_id", "units"])
    pool = db.capacity_pools.get(body["pool_id"])
    if pool is None:
        raise_err(ERR_NOT_FOUND, "pool not found")
    win = db.windows.get(body["window_id"])
    if win is None:
        raise_err(ERR_NOT_FOUND, "window not found")
    units = util.req_int(body["units"], "units", minimum=1)
    # Hold-time capacity check: raw total_units, no oversubscription
    if pool.get("committed_units", 0) + units > pool["total_units"]:
        raise_err(ERR_CAPACITY_INSUFFICIENT, "pool cannot satisfy requested units")
    now = clock.now()
    now_iso = clock.now_iso()
    res = {
        "id": util.new_id(),
        "pool_id": pool["id"],
        "window_id": win["id"],
        "units": units,
        "status": "HELD",
        "hold_expires_at": now + timedelta(seconds=calc.HOLD_TTL_SECONDS),
        "confirmed_at": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.capacity_reservations[res["id"]] = res
    pool["committed_units"] = pool.get("committed_units", 0) + units
    util.touch(pool)
    return res


def confirm_reservation(res):
    # ERR_HOLD_EXPIRED is stated as a time check ("a confirm attempted at or
    # after that instant"), so evaluate it against the hold's expiry even if
    # the automatic EXPIRED transition has not been applied to the row yet.
    now = clock.now()
    if res["status"] == "HELD" and not now < res["hold_expires_at"]:
        raise_err(ERR_HOLD_EXPIRED, "hold expired")
    if res["status"] != "HELD":
        raise_err(ERR_INVALID_STATE, "reservation not HELD")
    pool = db.capacity_pools.get(res["pool_id"])
    confirmable = calc.effective_pool_units(pool) - pool.get("committed_units", 0)
    if res["units"] > confirmable:
        raise_err(ERR_CAPACITY_INSUFFICIENT, "insufficient effective capacity at confirm")
    res["status"] = "CONFIRMED"
    res["confirmed_at"] = now
    util.touch(res)
    return res


def release_reservation(res):
    if res["status"] not in ("HELD", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, "reservation not in HELD or CONFIRMED")
    res["status"] = "RELEASED"
    util.touch(res)
    pool = db.capacity_pools.get(res["pool_id"])
    if pool is not None:
        pool["committed_units"] = pool.get("committed_units", 0) - res["units"]
        util.touch(pool)
    return res
