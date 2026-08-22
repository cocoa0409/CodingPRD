"""The administrative logical-clock endpoint (mounted outside /orchestra)."""

from flask import Blueprint

from db import db, iso
from middleware import endpoint
from response import ok
from validate import body, req_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "AdvertisingSales"])
def set_current_utc():
    data = body()
    moment = req_dt(data, "to_iso8601")
    db.clock = moment
    return ok({"current_utc": iso(moment)})
