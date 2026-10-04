"""The test-driving logical clock (PRD 2.8).

The clock reads exactly 2026-09-01T00:00:00Z at startup and never falls back to
wall-clock time. Only a PlatformAdmin may move it.
"""

import auth
import respond
import store
from errors import ApiError

ADMIN = ["PlatformAdmin"]


def register(app):
    @app.route("/carriers/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        uid, role = auth.actor()
        auth.require_role(uid, role, ADMIN)
        data = auth.body()
        auth.check_fields(data, ["current_utc"])
        raw = auth.string(data, "current_utc")
        store.CLOCK["now"] = store.parse_ts(raw)
        return respond.ok({"current_utc": store.now_iso()})