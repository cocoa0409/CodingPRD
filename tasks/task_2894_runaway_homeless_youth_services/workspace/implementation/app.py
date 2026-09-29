"""Runaway & Homeless Youth Services API - application entry point.

In-memory only: every table in store.py starts empty on every boot and nothing is
seeded, preloaded or hardcoded, so re-invoking start.sh wipes all state.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (
    admissions,
    education,
    governance,
    notifications,
    ops,
    programs,
    reunification,
    screenings,
    tlp,
    youths,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    programs,
    youths,
    screenings,
    admissions,
    notifications,
    reunification,
    tlp,
    education,
    governance,
    ops,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(envelope.error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(_exc):
    return (
        jsonify(envelope.error_body("ERR_INVALID_REQUEST", "Unknown resource path")),
        404,
    )


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return (
        jsonify(envelope.error_body("ERR_INVALID_REQUEST", "Method is not allowed on this path")),
        405,
    )


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 400:
        return (
            jsonify(envelope.error_body("ERR_INVALID_REQUEST", "Request body is malformed")),
            400,
        )
    return (
        jsonify(envelope.error_body("ERR_INVALID_REQUEST", exc.description or "Request failed")),
        exc.code or 500,
    )


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - defensive only
    return (
        jsonify(envelope.error_body("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)),
        500,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
