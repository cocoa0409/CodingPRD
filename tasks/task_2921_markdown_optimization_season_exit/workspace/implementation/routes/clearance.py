"""Clearance-space allocation and reservation release (PRD 3.7)."""

from flask import Blueprint

from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_MERCHANDISE_DIRECTOR, ROLE_PRICING_ANALYST, body,
                        endpoint)
from response import ok, ok_array
from serializers import reservation_json
from services import lookup
from services.lifecycle import (recompute_season, recompute_store,
                                reservations_of_plan)

bp = Blueprint("clearance", __name__)


@endpoint(bp, "/seasons/<season_id>/clearance-allocations", ["POST"],
          (ROLE_PRICING_ANALYST,))
def allocate_clearance(user_id, role, season_id):
    from validation import req_int, req_str
    payload = body()
    plan_id = req_str(payload, "markdown_plan_id")
    total_units = req_int(payload, "total_units", minimum=1)
    expected_season_version = req_int(payload, "expected_season_version",
                                      minimum=1)

    season = lookup.season(season_id)
    plan = lookup.plan(plan_id)

    if expected_season_version != season["version"]:
        raise ApiError("ERR_STALE_SEASON_VERSION",
                       "expected_season_version does not match the season.")

    lookup.gate_active(season)
    if plan["status"] not in ("APPROVED", "EXECUTING"):
        raise ApiError("ERR_PLAN_NOT_APPROVED",
                       "The plan must be APPROVED or EXECUTING to reserve "
                       "clearance space.")

    # step 0 (simulated): the supersede release of this plan's reservations
    superseded = [r for r in reservations_of_plan(plan)
                  if r["status"] in ("RESERVED", "COMMITTED")]
    freed_reserved = sum(r["reserved_units"] for r in superseded
                         if r["status"] == "RESERVED")
    freed_committed = sum(r["reserved_units"] for r in superseded
                          if r["status"] == "COMMITTED")
    freed_by_store = {}
    for reservation in superseded:
        freed_by_store[reservation["store_id"]] = \
            freed_by_store.get(reservation["store_id"], 0) + \
            reservation["reserved_units"]

    post_reserved = season["reserved_clearance_units"] - freed_reserved
    post_committed = season["committed_clearance_units"] - freed_committed

    # step 1: the chain ceiling, on post-release figures
    if post_reserved + post_committed + total_units > \
            season["clearance_space_units"]:
        raise ApiError("ERR_SEASON_CLEARANCE_CAP_EXCEEDED",
                       "The season's clearance_space_units cannot absorb the "
                       "request.")

    # steps 2 and 3: candidate stores, ordered
    candidates = []
    for store in db.stores.values():
        if store["status"] != "OPEN":
            continue
        available = store["available_clearance_units"] + \
            freed_by_store.get(store["id"], 0)
        if available < 1:
            continue
        candidates.append((available, store))
    candidates.sort(key=lambda pair: (-pair[0], pair[1]["store_number"],
                                      pair[1]["created_at"]))

    # step 4: the waterfall
    remaining = total_units
    plan_lines = []
    for available, store in candidates:
        if remaining <= 0:
            break
        take = available if available < remaining else remaining
        plan_lines.append((store, take))
        remaining -= take

    # step 5: all or nothing
    if remaining > 0:
        raise ApiError("ERR_CLEARANCE_SPACE_EXCEEDED",
                       "The open stores cannot absorb the whole allocation.")

    for reservation in superseded:
        reservation["status"] = "RELEASED"
        reservation["released_at"] = db.clock_instant()
        touch(reservation)

    created_rows = []
    rank = 0
    for store, units in plan_lines:
        rank += 1
        reservation = new_row(
            season_id=season["id"],
            store_id=store["id"],
            markdown_plan_id=plan["id"],
            reserved_units=units,
            allocation_rank=rank,
            released_at=None,
            status="RESERVED",
        )
        db.insert("reservations", reservation)
        created_rows.append(reservation)

    touched_stores = dict(freed_by_store)
    for store, units in plan_lines:
        touched_stores[store["id"]] = True
    for store_id in touched_stores:
        store = db.get("stores", store_id)
        if store is not None:
            recompute_store(store)

    recompute_season(season, force=True)
    return ok_array([reservation_json(r) for r in created_rows], status=201)


@endpoint(bp, "/clearance-reservations/<reservation_id>/release", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR))
def release_reservation(user_id, role, reservation_id):
    from validation import opt_str
    payload = body()
    opt_str(payload, "release_reason", max_len=1024)
    reservation = lookup.reservation(reservation_id)
    if reservation["status"] not in ("RESERVED", "COMMITTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RESERVED or COMMITTED reservation may be "
                       "released.")
    season = lookup.season(reservation["season_id"])
    lookup.gate_not_closed(season)

    reservation["status"] = "RELEASED"
    reservation["released_at"] = db.clock_instant()
    touch(reservation)

    store = db.get("stores", reservation["store_id"])
    if store is not None:
        recompute_store(store)
    recompute_season(season, force=True)
    return ok(reservation_json(reservation))
