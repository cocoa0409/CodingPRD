"""Logical clock and governance sweep endpoints (PRD sections 2.4 and 3.11)."""

from flask import Blueprint

import envelope
import governance as gov
import timeutil
import validate as v
from auth import ROLE_MANAGING_EDITOR, endpoint
from errors import ApiError
from store import store

bp = Blueprint("ops", __name__)


@bp.post("/editorial/_clock/set_current_utc")
@endpoint(ROLE_MANAGING_EDITOR)
def set_clock():
    body = v.body()
    current_utc = v.v_instant(body, "current_utc")
    # Rule 6 -- the clock never rewinds; an equal value is an accepted no-op.
    if current_utc < store.clock:
        raise ApiError("ERR_CLOCK_REWIND",
                       "requested instant is earlier than the current clock")
    store.clock = current_utc
    return envelope.ok({"current_utc": timeutil.fmt(store.clock)})


@bp.post("/editorial/_ops/governance-sweep")
@endpoint(ROLE_MANAGING_EDITOR)
def governance_sweep():
    return envelope.ok(gov.run_sweep())
