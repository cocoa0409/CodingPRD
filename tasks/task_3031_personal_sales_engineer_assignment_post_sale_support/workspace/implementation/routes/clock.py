"""The logical clock and the health probe.

PRD §2.6: the clock default is 2026-09-01T00:00:00Z and it never falls back to
real wall-clock time once set.  Advancing it is PlatformAdmin-only.
"""

from db import DB, iso, parse_dt
from middleware import guard
from response import as_str, body, ensure_known, invalid_value, ok_obj


def register(app):
    @app.route("/health", methods=["GET"])
    def health():
        # Exempt from identity headers entirely (PRD §2.1).
        return ok_obj({"status": "ok", "current_utc": iso(DB.clock)})

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        guard(["PlatformAdmin"])
        data = body()
        ensure_known(data, ["current_utc"])
        instant = parse_dt(as_str(data, "current_utc"))
        if instant is None:
            raise invalid_value("current_utc must be an ISO 8601 instant.")
        DB.clock = instant
        return ok_obj({"current_utc": iso(DB.clock)})