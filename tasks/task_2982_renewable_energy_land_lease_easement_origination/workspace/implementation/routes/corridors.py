"""Collection and interconnection corridors (PRD section 3.8, first half)."""

from flask import Blueprint

import access
import serializers as ser
import validation as v
from auth import LAND_AGENT, PORTFOLIO_MANAGER, require
from envelope import ok, ok_list
from errors import ERR_INVALID_STATE, fail
from store import db, insert, now, ordered, touch

bp = Blueprint("corridors", __name__, url_prefix="/land-origination")

VOLTAGE_CLASSES = ("COLLECTION_34_5KV", "GENTIE_138KV", "GENTIE_345KV")
READERS = (LAND_AGENT, PORTFOLIO_MANAGER)
DEFAULT_BUFFER_M = 50
MAX_BUFFER_M = 500


@bp.get("/corridors/<corridor_id>")
@require(*READERS)
def get_corridor(corridor_id):
    return ok(ser.corridor(access.corridor(corridor_id)))


@bp.get("/corridors")
@require(*READERS)
def list_corridors():
    limit, offset = v.pagination()
    rows = ordered(db.corridors.values())
    rows = v.apply_filters(rows, [
        ("status", v.query_str("status")),
        ("voltage_class", v.query_str("voltage_class")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.corridor, page), limit, offset, total)


@bp.post("/corridors")
@require(LAND_AGENT)
def create_corridor():
    body = v.json_body()
    route_name = v.req_str(body, "route_name", min_len=1, max_len=120)
    total_length_m = v.req_int(body, "total_length_m", lo=1)
    voltage_class = v.req_enum(body, "voltage_class", VOLTAGE_CLASSES)
    buffer_m = v.opt_int(body, "buffer_m", DEFAULT_BUFFER_M, lo=0,
                         hi=MAX_BUFFER_M)

    row = insert("corridors", {
        "route_name": route_name,
        "total_length_m": total_length_m,
        "voltage_class": voltage_class,
        "buffer_m": buffer_m,
        "permitted_at": None,
        "granted_crossing_count": 0,
        "status": "PLANNED",
    })
    return ok(ser.corridor(row), 201)


@bp.post("/corridors/<corridor_id>/permit")
@require(PORTFOLIO_MANAGER)
def permit_corridor(corridor_id):
    row = access.corridor(corridor_id)
    if row["status"] != "PLANNED":
        fail(ERR_INVALID_STATE)
    row["status"] = "PERMITTED"
    row["permitted_at"] = now()
    touch(row)
    return ok(ser.corridor(row))
