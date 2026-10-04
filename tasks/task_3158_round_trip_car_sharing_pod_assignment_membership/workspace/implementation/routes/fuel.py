"""Fuel-card transaction routes (PRD §4, §3.12)."""

from flask import Blueprint

import middleware as mw
from response import ok, created
from services import fuel as svc

bp = Blueprint("fuel", __name__)


def register(app):
    app.register_blueprint(bp)


@bp.post("/car-share/fuel-card-transactions")
def post_transaction():
    mw.authenticate(("Member", "PodOperator"))
    data = mw.body()
    row = svc.post_fuel_transaction(data, mw)
    return created(svc.serialize(row))


@bp.get("/car-share/fuel-card-transactions")
def list_transactions():
    mw.authenticate(("Member", "PodOperator"))
    limit, offset = mw.pagination()
    rows, meta = svc.list_fuel_transactions(mw.query("reservation_id"), mw.query("vehicle_id"),
                                            mw.query("status"), limit, offset)
    return ok([svc.serialize(r) for r in rows], response_type="array", pagination=meta)


@bp.get("/car-share/fuel-card-transactions/<transaction_id>")
def get_transaction(transaction_id):
    mw.authenticate(("Member", "PodOperator"))
    row = svc.get_transaction(transaction_id)
    return ok(svc.serialize(row))


@bp.post("/car-share/fuel-card-transactions/<transaction_id>/reverse")
def reverse_transaction(transaction_id):
    mw.authenticate(("PodOperator",))
    row = svc.reverse(transaction_id)
    return ok(svc.serialize(row))