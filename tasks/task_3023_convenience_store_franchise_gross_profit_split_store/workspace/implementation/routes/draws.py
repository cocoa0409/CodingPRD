"""DrawAdvance routes."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("draws", __name__)


@bp.post("/draws")
@middleware.auth(("FranchisorAdmin",))
def create_draw():
    payload = middleware.body(
        required=("franchisee_id", "store_id", "amount_cents", "drawn_on"),
    )
    franchisee = services.require_franchisee(payload["franchisee_id"])
    store = services.require_store(payload["store_id"])
    amount = middleware.positive_int(payload["amount_cents"], "amount_cents")
    drawn_on = timeutil.required_utc(payload["drawn_on"])

    projected = services.dec(franchisee["draw_outstanding_cents"]) + services.dec(amount)
    if projected > services.DRAW_CEILING_CENTS:
        fail("ERR_DRAW_EXCEEDS_LIMIT")

    record = db.insert("draws", {
        "franchisee_id": franchisee["id"],
        "store_id": store["id"],
        "amount_cents": amount,
        "drawn_on": drawn_on,
        "recovered_cents": Decimal("0.00"),
        "status": "ISSUED",
    })
    services.recalculate_franchisee(franchisee)
    return ok(schemas.dump("draws", record), 201)


@bp.get("/draws")
@middleware.auth(SHARED)
def list_draws():
    return list_records("draws", ("franchisee_id", "store_id", "status"))


@bp.get("/draws/<draw_id>")
@middleware.auth(SHARED)
def get_draw(draw_id):
    draw = services.require("draws", draw_id)
    return ok(schemas.dump("draws", draw))


@bp.post("/draws/<draw_id>/reverse")
@middleware.auth(("FranchisorAdmin",))
def reverse_draw(draw_id):
    draw = services.require("draws", draw_id)
    if draw["status"] not in ("ISSUED", "PARTIALLY_RECOVERED"):
        fail("ERR_INVALID_STATE")
    if services.dec(draw["recovered_cents"]) != 0:
        fail("ERR_DRAW_PARTIALLY_RECOVERED")
    draw["status"] = "REVERSED"
    db.touch(draw)
    franchisee = db.get("franchisees", draw["franchisee_id"])
    if franchisee is not None:
        services.recalculate_franchisee(franchisee)
    return ok(schemas.dump("draws", draw))