"""Community Risk Reduction Alarm Program API.

Entry point: blueprint registration, the error envelope handlers and the
foreground server the launcher hands off to.  The store is created empty on
every boot and nothing is ever seeded.
"""

import os
import threading

from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import canvass_routes
from routes import clock as clock_routes
from routes import crews as crew_routes
from routes import funding as funding_routes
from routes import households as household_routes
from routes import installations as installation_routes
from routes import plans as plan_routes
from routes import reports as report_routes
from routes import visits as visit_routes
from routes import zones as zone_routes

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

_lock = threading.Lock()

BLUEPRINTS = (
    clock_routes.bp,
    zone_routes.bp,
    household_routes.bp,
    crew_routes.bp,
    canvass_routes.bp,
    visit_routes.bp,
    funding_routes.bp,
    installation_routes.bp,
    plan_routes.bp,
    report_routes.bp,
)

for blueprint in BLUEPRINTS:
    app.register_blueprint(blueprint)


@app.before_request
def _serialize_requests():
    """Every mutation in this system touches several rows; serialize requests so
    the conserved ledgers of PRD 2.8 never interleave."""
    _lock.acquire()
    g._holds_lock = True


@app.teardown_request
def _release_lock(exc):
    if g.pop("_holds_lock", False):
        try:
            _lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_exception(exc):
    if exc.code == 404:
        return response.error(
            "ERR_INVALID_REQUEST", "Unknown resource path: %s." % request.path, 404
        )
    if exc.code == 405:
        return response.error(
            "ERR_INVALID_REQUEST",
            "Method %s is not allowed on %s." % (request.method, request.path),
            405,
        )
    if exc.code and exc.code < 500:
        return response.error("ERR_INVALID_REQUEST", exc.description, exc.code)
    return response.error("ERR_INVALID_REQUEST", exc.description, exc.code or 500)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return response.error("ERR_INVALID_REQUEST", str(exc), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
