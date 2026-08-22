from flask import Blueprint

import constants as C
import validators as V
from auth import authorize
from envelope import respond_object
from store import db, format_iso, parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(C.ALL_ROLES)
    payload = V.body()
    current_utc = V.req_datetime(payload, "current_utc")
    db.clock = parse_iso(current_utc)
    return respond_object({"current_utc": format_iso(db.clock)})
