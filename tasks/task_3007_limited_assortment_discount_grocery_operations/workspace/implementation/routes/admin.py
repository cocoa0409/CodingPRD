"""Administrative surface: the server logical clock."""
from flask import Blueprint

from core import body, db, endpoint, f_dt, fmt_dt, respond_object

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint("OperationsAdmin")
def set_clock():
    payload = body()
    current_utc = f_dt(payload, "to_iso8601")
    db.clock = current_utc
    return respond_object({"current_utc": fmt_dt(db.clock)})
