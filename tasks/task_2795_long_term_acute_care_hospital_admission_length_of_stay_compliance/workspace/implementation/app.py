"""LTCH Admission & Length-of-Stay Compliance API.

A fresh process starts with a completely empty in-memory store and a logical clock
reading 2026-08-01T00:00:00Z; nothing is seeded, preloaded or persisted to disk.
"""

import os
import threading
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, g

from clock import iso
from envelope import error_response
from errors import ApiError
from routes import payments, reference, referrals, reviews, stays, weaning

API_PREFIX = "/ltch"

# Requests are serialized so that read-modify-write sequences on the shared
# in-memory store stay atomic under a threaded WSGI server.
_store_lock = threading.RLock()


def _install_json_provider(app):
    try:
        from flask.json.provider import DefaultJSONProvider
    except ImportError:  # pragma: no cover - very old Flask
        return

    class ApiJSONProvider(DefaultJSONProvider):
        sort_keys = False

        @staticmethod
        def default(value):
            if isinstance(value, Decimal):
                return float(value)
            if isinstance(value, datetime):
                return iso(value)
            if isinstance(value, date):
                return value.isoformat()
            return DefaultJSONProvider.default(value)

    app.json = ApiJSONProvider(app)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    _install_json_provider(app)

    for module in (reference, referrals, stays, weaning, payments, reviews):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _acquire_store_lock():
        _store_lock.acquire()
        g._store_locked = True

    @app.teardown_request
    def _release_store_lock(exception=None):
        if getattr(g, "_store_locked", False):
            g._store_locked = False
            _store_lock.release()

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def _handle_not_found(error):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(error):
        return error_response("ERR_VALIDATION",
                              "The HTTP method is not allowed on this resource.", 405)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        app.logger.exception("Unhandled server error")
        return error_response("ERR_INTERNAL", "An unexpected server error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
