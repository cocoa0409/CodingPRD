"""Water Taxi & Harbor Shuttle API — entry point.

In-memory storage only; the store is empty on every boot and every entity is
built through the declared API surface.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_bookings
import routes_claims
import routes_days
import routes_estate
import routes_trips
from envelope import error_response
from errors import ApiError
from store import store

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_estate.bp)
app.register_blueprint(routes_days.bp)
app.register_blueprint(routes_trips.bp)
app.register_blueprint(routes_bookings.bp)
app.register_blueprint(routes_claims.bp)


@app.before_request
def _acquire_lock():
    # Serialise mutations.  The bounded wait guarantees a stuck request can never
    # deadlock the whole server for the rest of the process' life.
    g.holds_store_lock = store.lock.acquire(timeout=15)


@app.teardown_request
def _release_lock(exception=None):
    if getattr(g, "holds_store_lock", False):
        g.holds_store_lock = False
        try:
            store.lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(error):
    if error.code == 404:
        return error_response("ERR_INVALID_REQUEST", "Unknown route.", 404)
    if error.code == 405:
        return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
    if error.code == 400:
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
    return error_response("ERR_INVALID_REQUEST", str(error), error.code or 400)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    app.logger.exception("unhandled error")
    return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
