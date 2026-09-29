"""PRD 2.5 — the test-only logical site clock. The only endpoint with no auth headers."""

from flask import Blueprint

import store
from envelope import ok
from validation import Field, body

clock_bp = Blueprint("clock", __name__)


@clock_bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    values = body([Field("to_iso8601", "datetime")])
    store.set_clock(values["to_iso8601"])
    return ok({"current_utc": store.iso(store.now())})
