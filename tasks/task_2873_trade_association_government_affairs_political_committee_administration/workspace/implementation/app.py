"""Government Affairs & Political Committee Administration API.

Flask entry point: blueprint registration, the error envelope handlers and the
test-only logical clock endpoint (PRD 2.4).  The store is in-memory and starts
empty on every boot; nothing is ever seeded.
"""
import os

from flask import Flask

import routes_committees
import routes_grassroots
import routes_lobbying
import routes_members
import routes_pac
import routes_positions
import routes_reports
from constants import STAFF_ROLES
from core import (
    ApiError, authenticate, body, error_response, fail, format_instant, parse_instant,
    respond, set_clock,
)
from validate import get_str


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for module in (routes_members, routes_committees, routes_positions, routes_lobbying,
                   routes_reports, routes_grassroots, routes_pac):
        app.register_blueprint(module.bp)

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        authenticate(STAFF_ROLES)
        payload = body()
        raw = get_str(payload, "to_iso8601", max_len=64)
        moment = parse_instant(raw)
        if moment is None:
            fail("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 UTC instant.")
        set_clock(moment)
        return respond({"current_utc": format_instant(moment)})

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_exc):
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_405(_exc):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed on this route.", 405)

    @app.errorhandler(400)
    def handle_400(_exc):
        return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
