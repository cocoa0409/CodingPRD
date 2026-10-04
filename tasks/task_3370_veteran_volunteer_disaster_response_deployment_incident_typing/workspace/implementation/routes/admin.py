"""Test-driving endpoints (SystemAdmin only): the logical clock and the
ops-run housekeeping epoch.
"""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import timeutil
import opsrun

bp = Blueprint("admin", __name__)


@bp.post("/vdr/_clock/set_current_utc")
def set_current_utc():
    body = V.get_body()
    V.check_unknown(body, {"to_iso8601"})
    to_dt = V.req_dt(body, "to_iso8601")
    auth.require_roles("SystemAdmin")
    db.set_clock(to_dt)
    return envelope.ok({"current_utc": timeutil.fmt(to_dt)})


@bp.post("/vdr/_ops/run")
def run_ops_epoch():
    if V.get_body():
        errors.validation("the ops-run endpoint takes no fields")
    auth.require_roles("SystemAdmin")
    counts = opsrun.run_ops()
    return envelope.ok(counts)
