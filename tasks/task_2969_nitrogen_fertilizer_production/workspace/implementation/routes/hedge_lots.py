"""The gas hedge book (PRD 3.3). A lot's status is derived from what is left in it."""
from flask import Blueprint, request

import serialize
import validate as v
from auth import ALL_ROLES, COMMERCIAL_MANAGER, actor
from envelope import list_response, object_response, paging
from guards import duplicate, filtered, load
from store import db, stamp_new
from util import D

bp = Blueprint("hedge_lots", __name__)
PREFIX = "/nitrogen-ops/gas-hedge-lots"
LOT_STATUSES = ("OPEN", "CLOSED")


@bp.post(PREFIX)
def create_lot():
    actor([COMMERCIAL_MANAGER])
    body = v.get_body()
    plant_id = v.s_id(body, "plant_id")
    lot_code = v.s_code(body, "lot_code", 2, 16)
    volume = v.s_num(body, "mmbtu_volume", 1, gt=0)
    strike = v.s_num(body, "strike_price_usd_per_mmbtu", 4, gt=0)
    delivery_month = v.s_month(body, "delivery_month")
    load("plants", plant_id)
    duplicate("lots", "lot_code", lot_code, scope=("plant_id", plant_id))
    row = {
        "plant_id": plant_id,
        "lot_code": lot_code,
        "mmbtu_volume": volume,
        "strike_price_usd_per_mmbtu": strike,
        "delivery_month": delivery_month,
        "consumed_mmbtu": D("0.0"),
        "status": "OPEN",
        # Volumes drawn by each settlement, so a reopen can hand them back.
        "_draws": {},
    }
    stamp_new(row)
    db.lots[row["id"]] = row
    return object_response(serialize.lot_json(row), 201)


@bp.get(PREFIX + "/<id>")
def get_lot(id):
    actor(ALL_ROLES)
    return object_response(serialize.lot_json(load("lots", id)))


@bp.get(PREFIX)
def list_lots():
    actor(ALL_ROLES)
    limit, offset = paging(request.args)
    rows = filtered("lots", [
        ("plant_id", v.query_str("plant_id")),
        ("status", v.query_enum("status", LOT_STATUSES)),
        ("delivery_month", v.query_str("delivery_month")),
    ])
    return list_response(serialize.dump("lots", rows), limit, offset)
