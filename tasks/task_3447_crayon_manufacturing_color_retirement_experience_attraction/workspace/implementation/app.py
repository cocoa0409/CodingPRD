"""Crayon Works API — application factory and entry point.

All 36 business endpoints live under /crayon-works; the logical-clock
capability is the single unprefixed endpoint (PRD section 2.4).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import allocations
import colors_votes
import epoch
import formulas_safety
import licensed
import pigments_recall
import runs
import sessions_tickets
import specs
from constants import ROLE_PLATFORM_ADMIN
from envelope import error_response, ok
from errors import ApiError
from store import STORE
from validation import auth, body, req_str, require_role


def set_clock():
    """POST /_clock/set_current_utc — set the logical clock (unprefixed)."""
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    to_iso8601 = req_str(data, "to_iso8601")
    try:
        STORE.set_clock(to_iso8601)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    return ok({"current_utc": STORE.clock_raw})


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    colors_votes.register(app)
    pigments_recall.register(app)
    formulas_safety.register(app)
    specs.register(app)
    runs.register(app)
    allocations.register(app)
    licensed.register(app)
    sessions_tickets.register(app)
    epoch.register(app)
    app.add_url_rule("/_clock/set_current_utc", view_func=set_clock, methods=["POST"])

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        # Unknown route / wrong method still answer in the envelope.
        if err.code == 404:
            return error_response("ERR_NOT_FOUND", "resource does not exist", 404)
        if err.code == 405:
            return error_response("ERR_INVALID_REQUEST", "method not allowed", 400)
        return error_response("ERR_INVALID_REQUEST", err.description, err.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", "unexpected error: %s" % err, 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
