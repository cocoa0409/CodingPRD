"""Municipal Credit Ratings API — Flask entry point.

Mounts all business endpoints under /muni plus the platform logical-clock
endpoint at /_clock/set_current_utc. Storage is in-memory only and starts
empty on every boot; the harness re-launches this process per test.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body, error_response
from errors import ApiError
import routes_appeals
import routes_bondsales
import routes_clock
import routes_criteria
import routes_engagements
import routes_obligations
import routes_ratings
import routes_registry
import routes_reviewitems
import routes_scorecards
import routes_sessions
import routes_votes

app = Flask(__name__)

for module in (
    routes_clock,
    routes_registry,
    routes_engagements,
    routes_scorecards,
    routes_criteria,
    routes_sessions,
    routes_votes,
    routes_ratings,
    routes_appeals,
    routes_obligations,
    routes_bondsales,
    routes_reviewitems,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    # Routing-level failures (unknown path, wrong method) still answer in the
    # standard error envelope.
    error_id = "ERR_INVALID_REQUEST"
    if exc.code == 404:
        error_id = "ERR_NOT_FOUND"
    elif exc.code == 405:
        error_id = "ERR_METHOD_NOT_ALLOWED"
    return jsonify(error_body(error_id, exc.name)), exc.code or 500


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(error_body("ERR_INTERNAL", "internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
