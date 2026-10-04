"""Routes: trade partners and capacity commitments."""

from flask import Blueprint

from db import db, iso3
from errors import ApiError
from helpers import (
    auth, require_role, body, idem_begin, require_fields, dt_field,
    fresh_row, touch, get_or_404,
)
from response import success_obj, success_list
import services as svc

bp = Blueprint("trade", __name__)

TRADES = ["FRAMING", "PLUMBING", "ELECTRICAL", "HVAC", "MASONRY"]


@bp.post("/trade-partners")
def create_trade_partner():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["DIVISION_PRESIDENT"])
    b = body()
    require_fields(b, [
        ("name", "string", None, False),
        ("trade", "string", TRADES, False),
    ])
    row = fresh_row()
    row.update({"name": b["name"], "trade": b["trade"]})
    db.trade_partners[row["id"]] = row
    return success_obj(svc.ser_trade_partner(row), status=201)


@bp.get("/trade-partners/<tid>")
def get_trade_partner(tid):
    auth()
    tp = get_or_404(db.trade_partners, tid)
    return success_obj(svc.ser_trade_partner(tp))


@bp.post("/trade-partners/<tid>/capacity-commitments")
def create_capacity_commitment(tid):
    role, user_id = auth()
    ctx = idem_begin()
    tp = get_or_404(db.trade_partners, tid)
    # 5: role + self-scope
    require_role(role, ["TRADE_PARTNER"])
    if user_id != tid:
        raise ApiError(
            "ERR_FORBIDDEN", 403,
            "TRADE_PARTNER may act only on its own commitments",
        )
    b = body()
    require_fields(b, [
        ("community_id", "string", None, False),
        ("period_start", "datetime", None, False),
        ("period_end", "datetime", None, False),
        ("committed_units", "integer", None, False),
    ])
    get_or_404(db.communities, b["community_id"])
    period_start = dt_field(b, "period_start")
    period_end = dt_field(b, "period_end")
    # 8: half-open overlap check for same partner + same community
    for cc in db.capacity_commitments.values():
        if cc["trade_partner_id"] != tid:
            continue
        if cc["community_id"] != b["community_id"]:
            continue
        ex_start = svc.dt_or_none(cc["period_start"])
        ex_end = svc.dt_or_none(cc["period_end"])
        if period_start < ex_end and ex_start < period_end:
            raise ApiError(
                "ERR_CAPACITY_PERIOD_OVERLAP", 409,
                "Commitment period overlaps an existing commitment",
            )
    row = fresh_row()
    row.update({
        "trade_partner_id": tid,
        "community_id": b["community_id"],
        "period_start": iso3(period_start),
        "period_end": iso3(period_end),
        "committed_units": b["committed_units"],
        "allocated_units": 0,
    })
    db.capacity_commitments[row["id"]] = row
    return success_obj(svc.ser_capacity_commitment(row), status=201)


@bp.get("/trade-partners/<tid>/capacity-commitments")
def list_partner_commitments(tid):
    auth()
    get_or_404(db.trade_partners, tid)
    items = [c for c in db.capacity_commitments.values() if c["trade_partner_id"] == tid]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return success_list([svc.ser_capacity_commitment(c) for c in items])


@bp.get("/capacity-commitments/<cid>")
def get_capacity_commitment(cid):
    auth()
    cc = get_or_404(db.capacity_commitments, cid)
    return success_obj(svc.ser_capacity_commitment(cc))


@bp.post("/capacity-commitments/<cid>/reduce")
def reduce_capacity_commitment(cid):
    role, user_id = auth()
    ctx = idem_begin()
    cc = get_or_404(db.capacity_commitments, cid)
    # 5: role + self-scope
    require_role(role, ["TRADE_PARTNER"])
    if user_id != cc["trade_partner_id"]:
        raise ApiError(
            "ERR_FORBIDDEN", 403,
            "TRADE_PARTNER may act only on its own commitments",
        )
    b = body()
    require_fields(b, [("new_committed_units", "integer", None, False)])
    new_units = b["new_committed_units"]
    if new_units < cc["allocated_units"]:
        raise ApiError(
            "ERR_CAPACITY_BELOW_ALLOCATED", 409,
            "Reduction would put committed_units below allocated_units",
        )
    cc["committed_units"] = new_units
    touch(cc)
    return success_obj(svc.ser_capacity_commitment(cc))
