"""Instrument endpoints (PRD 3.4): listing, fetch, bank intake."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import STORE, touch
from envelope import ok, paged
from errors import raise_err
from serialize import instrument as ser_instrument
from validate import get_body  # noqa: F401  (intake takes no body)

bp = Blueprint("instruments", __name__, url_prefix="/piano-works")


def _get_instrument(iid):
    i = STORE["instruments"].get(iid)
    if i is None:
        raise_err("ERR_NOT_FOUND", "instrument %s not found" % iid)
    return i


@bp.get("/instruments")
def list_instruments():
    authenticate(ALL_ROLES)
    items = list(STORE["instruments"].values())
    for field in ("status", "condition_grade", "model", "build_order_id"):
        v = request.args.get(field)
        if v is not None:
            items = [i for i in items if i[field] == v]
    return paged(items, ser_instrument)


@bp.get("/instruments/<iid>")
def get_instrument(iid):
    authenticate(ALL_ROLES)
    return ok(ser_instrument(_get_instrument(iid)))


@bp.post("/instruments/<iid>/bank-intake")
def bank_intake(iid):
    authenticate(("ArtistLiaison",))
    i = _get_instrument(iid)
    if (
        i["status"] != "SHOWROOM"
        or not i["certified_authentic"]
        or i["condition_grade"] not in ("A", "B")
    ):
        raise_err(
            "ERR_INSTRUMENT_NOT_BANK_ELIGIBLE",
            "bank intake requires SHOWROOM, certified authentic, grade A or B",
        )
    i["status"] = "BANK"
    touch(i)
    return ok(ser_instrument(i))
