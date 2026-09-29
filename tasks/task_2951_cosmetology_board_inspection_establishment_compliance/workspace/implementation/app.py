"""Cosmetology Board Compliance API — application entry point.

The store is in-memory only and starts completely empty on every boot: nothing
is seeded, preloaded or persisted anywhere.
"""
import os

from flask import Flask, g

import envelope
import store
from errors import ApiError

from routes_reads import reads_bp
from routes_registry import registry_bp
from routes_facility import facility_bp
from routes_inspection import inspection_bp
from routes_enforcement import enforcement_bp
from routes_health import health_bp, clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for bp in (reads_bp, registry_bp, facility_bp, inspection_bp, enforcement_bp, health_bp):
        app.register_blueprint(bp, url_prefix="/cosmetology")
    app.register_blueprint(clock_bp)

    @app.before_request
    def _acquire():
        store.LOCK.acquire()
        g._locked = True

    @app.teardown_request
    def _release(exc=None):
        if g.pop("_locked", False):
            try:
                store.LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.err(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _no_route(exc):
        return envelope.err("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def _no_method(exc):
        return envelope.err("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(400)
    def _bad_request(exc):
        return envelope.err("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.err(exc.error_id, exc.message, exc.http_status)
        return envelope.err("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
