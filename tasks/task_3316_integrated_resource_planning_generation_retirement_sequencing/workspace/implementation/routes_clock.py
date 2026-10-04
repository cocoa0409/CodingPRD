"""Logical clock endpoint: POST /_clock/set_current_utc."""

from flask import Blueprint, request

from db import store
from errors import ERR_INVALID_REQUEST, raise_error
from helpers import touch
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("UtilityPlanner", "PlatformAdmin")
def set_clock(user_id, role):
    payload = request.get_json(silent=True) or {}
    to_iso = payload.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso.strip():
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        store.clock.set(to_iso)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant")
    # Side effect: auto-retire DECIDED resources whose retirement_year has arrived.
    new_year = store.clock.year()
    for r in store.resources.values():
        if r["status"] == "DECIDED" and r.get("retirement_year") is not None \
                and r["retirement_year"] <= new_year:
            r["status"] = "RETIRED"
            touch(r)
    return success_object({"current_utc": store.clock.now_iso()}, 200)
