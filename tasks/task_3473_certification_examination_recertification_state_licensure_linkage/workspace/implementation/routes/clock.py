"""POST /_clock/set_current_utc — the logical clock, mounted OUTSIDE the
/registry prefix (PRD §2.5)."""

from flask import Blueprint

from db import STORE
from envelope import ok_object
from errors import raise_err
from middleware import authn, body
from services.sweep import run_sweep
from util import fmt_dt, parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authn(["RegistryAdmin"])
    b = body()
    target = parse_datetime(b.get("to_iso8601"))
    if target is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'to_iso8601' is required and must be an ISO-8601 timestamp")
    if target < STORE.clock:
        raise_err("ERR_CLOCK_REGRESSION",
                  "Cannot move the logical clock backwards from %s" % fmt_dt(STORE.clock))
    STORE.clock = target
    counters = run_sweep(target)
    payload = {"current_utc": fmt_dt(target)}
    payload.update(counters)
    return ok_object(payload, 200)
