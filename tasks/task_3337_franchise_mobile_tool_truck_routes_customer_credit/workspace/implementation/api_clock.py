"""The logical clock capability."""

from flask import Blueprint

import auth
import clock
import envelope
import recompute

bp = Blueprint("clock", __name__, url_prefix="/retail")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require("PlatformAdmin")
    payload = envelope.body()
    envelope.require(payload, "current_utc")
    instant = clock.parse_utc(payload["current_utc"])
    clock.set_now(instant)
    # Evaluating the clock is not a pure read: the sweep runs for every
    # non-CLOSED account at the newly accepted instant.
    recompute.run_sweeps()
    return envelope.ok({
        "current_utc": clock.fmt_week(clock.now()),
        "current_week_start": clock.fmt_week(clock.current_week_start()),
    })
