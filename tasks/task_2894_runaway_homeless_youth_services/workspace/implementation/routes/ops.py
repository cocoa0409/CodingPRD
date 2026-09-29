"""The two administrative test-driving capabilities (PRD 2.5 and 3.10)."""

from flask import Blueprint

import authz
import cascade
import envelope
import shape
import store
from errors import fail

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authz.require(authz.PROGRAM_ADMIN)
    body = shape.body()
    target = shape.need_instant(body, "to_iso8601")

    # Ladder 33 - "the clock is strictly monotonic".
    if target <= store.now():
        fail("ERR_CLOCK_MONOTONIC_VIOLATION")

    previous = store.set_clock(target)
    # "moving the clock mutates no entity and runs no census"
    return envelope.ok(
        {
            "current_utc": store.iso(store.now()),
            "previous_utc": store.iso(previous),
        }
    )


@bp.post("/_ops/nightly-census")
def nightly_census():
    authz.require(authz.PROGRAM_ADMIN)
    counts = cascade.run_census()
    return envelope.ok(counts)
