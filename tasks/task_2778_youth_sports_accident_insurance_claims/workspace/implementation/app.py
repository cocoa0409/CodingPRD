"""Youth Sports Accident Insurance Claims API -- Flask application entry point.

All state lives in plain in-memory dicts (see db.py). Nothing is ever seeded:
every entity in this system is built through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
import routes_activity
import routes_claim
import routes_master
import routes_policy
import routes_roster
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_master.bp)
app.register_blueprint(routes_policy.bp)
app.register_blueprint(routes_roster.bp)
app.register_blueprint(routes_activity.bp)
app.register_blueprint(routes_claim.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return response.respond_error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    status = exc.code or 500
    if status == 404:
        return response.respond_error("ERR_INVALID_REQUEST", "Unknown resource path", 404)
    if status == 405:
        return response.respond_error(
            "ERR_INVALID_REQUEST", "Method not allowed for this path", 405
        )
    if status == 415:
        return response.respond_error(
            "ERR_INVALID_REQUEST", "Request body must be JSON", 400
        )
    if status == 400:
        return response.respond_error("ERR_INVALID_REQUEST", "Malformed request", 400)
    return response.respond_error("ERR_INVALID_REQUEST", exc.description or "Error", status)


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover -- defensive
    app.logger.exception("unhandled error: %s", exc)
    return response.respond_error("ERR_INVALID_REQUEST", "Internal error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
