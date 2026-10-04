"""Entry point, request lifecycle sweeps and error handlers.

The store starts empty on every boot: nothing is seeded, preloaded or hardcoded.
Every entity a client needs is built through the declared API surface.
"""
import os

from flask import Flask, request

import db
import routes
from errors import ApiError
from response import error as error_response
from services import dose as dose_svc, program as program_svc

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

routes.register(app)


# ---------------------------------------------------------------------------
# Time-derived state is refreshed on the next read: the sweeps below run before
# each request so that lot expiration, dose misses and their cascades are
# consistent with the logical clock without any client action.
# ---------------------------------------------------------------------------
SWEEP_PREFIXES = ("/otp/",)


@app.before_request
def refresh_time_derived_state():
    if not request.path.startswith(SWEEP_PREFIXES):
        return None
    try:
        dose_svc.sweep_missed_doses()
        program_svc.refresh_all_programs(bump=False)
    except ApiError:
        pass
    return None


# ---------------------------------------------------------------------------
# Error handling (PRD 2.2)
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response("ERR_INVALID_REQUEST", "No route matches this request", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed for this route", 405)


@app.errorhandler(500)
def handle_500(exc):
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)


@app.errorhandler(Exception)
def handle_generic(exc):
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        if exc.code == 415 or exc.code == 400:
            return error_response(
                "ERR_INVALID_REQUEST", "Malformed request body", 400
            )
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed", exc.code
        )
    app.logger.exception("unhandled error: %s", exc)
    return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)