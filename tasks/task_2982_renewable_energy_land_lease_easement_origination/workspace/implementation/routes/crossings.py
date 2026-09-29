"""Crossing agreements (PRD section 3.8, middle).

The proposal's rejection order is rung 4 (parcel) before rung 9 (corridor),
then shape, then the station range (17) and the window range (18), then title
compliance (26) and only last the corridor conflict (38): title outranks
scheduling.
"""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import LAND_AGENT, PAYMENT_ADMINISTRATOR, PORTFOLIO_MANAGER, require
from envelope import ok, ok_list
from errors import (
    ERR_CORRIDOR_NOT_PERMITTED,
    ERR_CORRIDOR_STATION_CONFLICT,
    ERR_INVALID_STATE,
    ERR_INVALID_STATION_RANGE,
    ERR_INVALID_WINDOW_RANGE,
    ERR_TITLE_CURATIVE_BLOCKING,
    fail,
)
from store import db, insert, now, ordered, touch

bp = Blueprint("crossings", __name__, url_prefix="/land-origination")

CROSSING_KINDS = ("COLLECTION_LINE", "INTERCONNECTION_ROUTE", "ACCESS_ROAD")
READERS = (LAND_AGENT, PORTFOLIO_MANAGER, PAYMENT_ADMINISTRATOR)
LIVE_STATUSES = ("PROPOSED", "GRANTED")


@bp.get("/crossing-agreements/<crossing_id>")
@require(*READERS)
def get_crossing(crossing_id):
    return ok(ser.crossing(access.crossing(crossing_id)))


@bp.get("/crossing-agreements")
@require(*READERS)
def list_crossings():
    limit, offset = v.pagination()
    rows = ordered(db.crossings.values())
    rows = v.apply_filters(rows, [
        ("corridor_id", v.query_str("corridor_id")),
        ("parcel_id", v.query_str("parcel_id")),
        ("crossing_kind", v.query_str("crossing_kind")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.crossing, page), limit, offset, total)


def _conflicts(corridor, station_start, station_end, window_start, window_end):
    """Buffer-expanded station overlap AND half-open time overlap, on the same
    corridor only. Touching exactly at the buffer edge is not a conflict, and
    abutting windows are not a conflict."""
    buffer_m = int(corridor["buffer_m"])
    for other in cascades.corridor_crossings(corridor["id"]):
        if other["status"] not in LIVE_STATUSES:
            continue
        if not (station_start < int(other["station_end_m"]) + buffer_m
                and station_end + buffer_m > int(other["station_start_m"])):
            continue
        if window_start < other["occupancy_window_end"] \
                and window_end > other["occupancy_window_start"]:
            return True
    return False


@bp.post("/crossing-agreements")
@require(LAND_AGENT)
def create_crossing():
    body = v.json_body()
    # Rung 4 outranks rung 9, and both outrank the rung-14 shape pass.
    parcel_id = v.lookup_fk(body, "parcel_id")
    parcel = access.parcel(parcel_id) if parcel_id else None
    corridor_id = v.lookup_fk(body, "corridor_id")
    corridor = access.corridor(corridor_id) if corridor_id else None

    v.req_fk(body, "parcel_id")
    v.req_fk(body, "corridor_id")
    crossing_kind = v.req_enum(body, "crossing_kind", CROSSING_KINDS)
    station_start = v.req_int(body, "station_start_m")
    station_end = v.req_int(body, "station_end_m")
    window_start = v.req_dt(body, "occupancy_window_start")
    window_end = v.req_dt(body, "occupancy_window_end")

    if station_start < 0 or station_end <= station_start \
            or station_end > int(corridor["total_length_m"]):
        fail(ERR_INVALID_STATION_RANGE)
    if window_end <= window_start:
        fail(ERR_INVALID_WINDOW_RANGE)
    if int(parcel["blocking_curative_open_count"]) > 0:
        fail(ERR_TITLE_CURATIVE_BLOCKING)
    if _conflicts(corridor, station_start, station_end, window_start, window_end):
        fail(ERR_CORRIDOR_STATION_CONFLICT)

    occupied_m = station_end - station_start
    days = calc.duration_days(window_start, window_end)
    surcharge_bps, compensation = calc.crossing_compensation(
        crossing_kind, occupied_m, days)

    row = insert("crossings", {
        "corridor_id": corridor["id"],
        "parcel_id": parcel["id"],
        "crossing_kind": crossing_kind,
        "station_start_m": station_start,
        "station_end_m": station_end,
        "occupancy_window_start": window_start,
        "occupancy_window_end": window_end,
        "occupied_m": occupied_m,
        "duration_days": days,
        "long_occupancy_surcharge_bps": surcharge_bps,
        "compensation_cents": compensation,
        "granted_at": None,
        "status": "PROPOSED",
    })
    return ok(ser.crossing(row), 201)


@bp.post("/crossing-agreements/<crossing_id>/grant")
@require(PORTFOLIO_MANAGER)
def grant_crossing(crossing_id):
    row = access.crossing(crossing_id)
    corridor = db.corridors.get(row["corridor_id"])

    if row["status"] != "PROPOSED":
        fail(ERR_INVALID_STATE)
    if corridor is None or corridor["status"] != "PERMITTED":
        fail(ERR_CORRIDOR_NOT_PERMITTED)

    row["status"] = "GRANTED"
    row["granted_at"] = now()
    touch(row)

    cascades.recount_granted_crossings(corridor)
    touch(corridor)
    return ok(ser.crossing(row))
