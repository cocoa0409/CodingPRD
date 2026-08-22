"""Sterilization Services & Lot Release API.

Entry point: registers the route blueprints, installs the standard error
envelope handlers and serves on 0.0.0.0:$PORT in the foreground.

The in-memory store starts completely empty on every boot; no entity is ever
seeded, preloaded or hardcoded here.
"""

import os
import threading

from flask import Flask, g

import response
from errors import ApiError
from routes.cycles import bp as cycles_bp
from routes.lots import bp as lots_bp
from routes.misc import bp as misc_bp
from routes.positions import bp as positions_bp
from routes.reference import bp as reference_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(reference_bp)
app.register_blueprint(lots_bp)
app.register_blueprint(cycles_bp)
app.register_blueprint(positions_bp)
app.register_blueprint(misc_bp)

_request_lock = threading.Lock()


@app.before_request
def _serialize_requests():
    _request_lock.acquire()
    g._store_lock_held = True


@app.teardown_request
def _release_lock(exception=None):
    if getattr(g, "_store_lock_held", False):
        g._store_lock_held = False
        try:
            _request_lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return response.error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def _handle_not_found(error):
    return response.error_response(
        "ERR_VALIDATION", "No such route on this API.", 404)


@app.errorhandler(405)
def _handle_method_not_allowed(error):
    return response.error_response(
        "ERR_VALIDATION", "Method not allowed for this route.", 405)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return _handle_api_error(error)
    app.logger.exception("unhandled error")
    return response.error_response(
        "ERR_VALIDATION", "Unexpected server error: %s" % error, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
