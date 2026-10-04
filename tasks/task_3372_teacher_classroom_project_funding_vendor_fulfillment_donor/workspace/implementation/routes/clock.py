"""Test-driving endpoints, outside the /giving business surface:
POST /_clock/set_current_utc and POST /_sweeps/expiration_run.
Both are PlatformAdmin-only."""
import store
from envelope import ok
from errors import bad_request
from security import actor, require_roles
from services import sweeps
from util_time import iso_sec, parse_dt
from validators import json_body, require_present


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        data = json_body()
        raw = require_present(data, "current_utc")
        moment = parse_dt(raw)
        if moment is None:
            raise bad_request("current_utc must be an ISO 8601 timestamp")
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        store.set_logical_now(moment)
        return ok({"current_utc": iso_sec(moment)}, 200)

    @app.route("/_sweeps/expiration_run", methods=["POST"])
    def expiration_run():
        _, role = actor()
        require_roles(role, ("PlatformAdmin",))
        summary = sweeps.expiration_run(store.logical_now())
        return ok(summary, 200)
