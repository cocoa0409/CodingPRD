"""The test-driving clock endpoint.

Moving the clock is not passive: it re-evaluates the time-driven transitions,
most notably the expiry of an approved course audit whose term has ended.
"""

import auth
import clock
from core import app, body, str_field
from response import ok
from routes_audits import expire_due_audits


@app.route("/ap-program/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth.authenticate(["PlatformAdmin"])
    payload = body()
    to_iso8601 = str_field(payload, "to_iso8601")
    clock.set_current(to_iso8601)
    expire_due_audits()
    return ok({"current_utc": clock.now_iso()})
