"""Animal ID Traceability API - entry point.

The store is in-memory and starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

import derive
from db import store
from errors import ApiError
from respond import error
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    @app.before_request
    def _acquire_store_lock():
        store.lock.acquire()
        derive.reset_pending()

    @app.after_request
    def _flush_derived(response):
        # Producer-level figures sit at the top of every cascade; flushing the
        # collected marks once leaves the record with a single version bump.
        derive.flush_producers()
        return response

    @app.teardown_request
    def _release_store_lock(exc=None):
        try:
            store.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error("ERR_NOT_FOUND", "Method not allowed for this resource", 405)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error(exc.error_id, exc.message, exc.http_status)
        return error("ERR_INTERNAL", "Internal server error", 500)

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
