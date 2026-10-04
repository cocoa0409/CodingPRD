"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

import envelope
import store
from authz import authenticate, authorize
from errors import err
from validate import parse_body, validate

bp = Blueprint("clock", __name__)


@bp.route("/foundry/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    vals = validate(parse_body(), [{"name": "to_iso8601", "kind": "datetime"}])
    target = vals["to_iso8601"]
    current = store.now()
    if not target > current:
        raise err(
            "ERR_INVALID_REQUEST", "to_iso8601 must be strictly after the current logical time"
        )
    crosses_month = (target.year, target.month) != (current.year, current.month)
    store.set_now(target)
    if crosses_month:
        # Period rollover (PRD 2.4): reset counters, WARNING -> ACTIVE,
        # sand month-to-date rate resets (current_sand_rate is computed live).
        # BREACH / REMEDIATION are deliberately not cleared.
        for p in store.db["permits"].values():
            p["over_limit_reading_count_current_period"] = 0
            if p["status"] == "WARNING":
                p["status"] = "ACTIVE"
                store.touch(p)
    return envelope.success({"current_utc": store.iso()})
