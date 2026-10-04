"""Logical clock and week epoch roll (PRD section 2.9)."""

from flask import Blueprint

import auth
import db
import services
from envelope import ok
from errors import ERR_INVALID_REQUEST, fail
from helpers import json_body, require_str

bp = Blueprint("clock", __name__)

ADMIN = auth.ROLE_ADMIN


def _is_new_week(previous_start, instant):
    """True when the supplied instant crosses a week boundary."""
    if previous_start is None:
        return True
    return (instant - previous_start).total_seconds() >= 7 * 24 * 3600


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))

    body = json_body()
    raw = require_str(body, "current_utc")
    instant = db.parse_dt(raw)
    if instant is None:
        fail(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 instant.")

    epoch = db.open_epoch()
    previous_start = epoch.get("starts_at_utc")
    crossed = _is_new_week(previous_start, instant)

    db.set_clock(instant)

    if crossed and instant > previous_start:
        services.roll_week_epoch(instant)

    # Advancing the clock re-evaluates the resolver for every waiting piece and
    # fires the rework-window and appeal-deadlock sweeps deterministically.
    services.quorum_timeout_sweep()
    services.rework_timeout_sweep()
    services.appeal_deadlock_sweep()

    return ok({})