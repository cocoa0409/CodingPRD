"""The server's logical clock (PRD 2.4)."""

from flask import Blueprint

from auth import endpoint
from envelope import ok
from errors import ApiError
from store import db, parse_iso_instant
from validators import body, require_fields

bp = Blueprint("clock", __name__)


@bp.post("/adjudication/_clock/set_current_utc")
@endpoint(["PlanAdmin"])
def set_clock():
    payload = body()
    require_fields(payload, ["to_iso8601"])
    moment = parse_iso_instant(payload["to_iso8601"])
    if moment is None:
        raise ApiError("ERR_INVALID_FIELD_VALUE", "to_iso8601 is not a valid ISO 8601 instant.")
    db.set_clock(moment)
    return ok({})
