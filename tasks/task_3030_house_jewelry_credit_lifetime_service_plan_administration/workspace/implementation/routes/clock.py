"""The logical clock: POST /_clock/set_current_utc."""

from db import DB, iso, parse_dt
from middleware import guard
from response import as_str, body, ok_obj, bad_request


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        guard(["ChainAdmin"])
        data = body()
        text = as_str(data, "to_iso8601")
        instant = parse_dt(text)
        if instant is None:
            raise bad_request("to_iso8601 must be an ISO 8601 instant.")
        DB.clock = instant
        return ok_obj({"current_utc": iso(DB.clock)})