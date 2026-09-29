"""Logical UTC clock endpoints."""

from flask import Blueprint

import db
import response
import validation
from middleware import OPAQUE_ROLES, endpoint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlantAdmin"])
def set_current_utc():
    body = validation.json_body()
    current_utc = validation.timestamp(body, "current_utc", required=True)
    db.db.clock = current_utc
    return response.ok({})


@bp.get("/_clock")
@endpoint(OPAQUE_ROLES)
def read_clock():
    return response.ok({"current_utc": db.fmt_ts(db.db.now())})
