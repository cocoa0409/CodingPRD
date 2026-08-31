"""Lubricant Blending & Packaging API - entry point."""
import os
import threading

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import core
from core import ApiError, error_body

import routes_batches
import routes_claims
import routes_commerce
import routes_formulation
import routes_master
import routes_packaging

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(routes_master.bp)
app.register_blueprint(routes_formulation.bp)
app.register_blueprint(routes_batches.bp)
app.register_blueprint(routes_claims.bp)
app.register_blueprint(routes_packaging.bp)
app.register_blueprint(routes_commerce.bp)

_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()
    g._lock_held = True


@app.teardown_request
def _release_lock(exc=None):
    if getattr(g, "_lock_held", False):
        g._lock_held = False
        try:
            _LOCK.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.status


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    error_id = "ERR_INVALID_REQUEST"
    if exc.code == 404:
        error_id = "ERR_NOT_FOUND"
    elif exc.code == 405:
        error_id = "ERR_METHOD_NOT_ALLOWED"
    return jsonify(error_body(error_id, exc.description or "")), exc.code


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return jsonify(error_body("ERR_INTERNAL", str(exc))), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
