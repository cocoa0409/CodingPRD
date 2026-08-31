"""Food Hub Aggregation Cooperative API — entry point.

State lives only in process memory (see store.py); a fresh process therefore
starts with an entirely empty store.  Nothing is seeded, preloaded, registered
or hardcoded at startup: every entity the tests need is built through the
declared endpoints.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ERROR_HTTP_STATUS, ApiError
from store import request_lock

import routes_catalog
import routes_claims
import routes_delivery
import routes_dock
import routes_governance
import routes_orders
import routes_producers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_producers.bp)
    app.register_blueprint(routes_catalog.bp)
    app.register_blueprint(routes_orders.bp)
    app.register_blueprint(routes_dock.bp)
    app.register_blueprint(routes_delivery.bp)
    app.register_blueprint(routes_claims.bp)
    app.register_blueprint(routes_governance.bp)

    @app.before_request
    def _begin():
        # Serialise request handling so cascades and rollups observe a
        # consistent store; also scopes the per-request "touched once" set.
        request_lock.acquire()
        g._touched = set()

    @app.teardown_request
    def _end(_exc=None):
        try:
            request_lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_PRODUCER_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
