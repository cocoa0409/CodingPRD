"""Entry point for the Sponsored Internship Placement API.

Storage is in-memory only: the store starts empty on every boot and no entity
is ever seeded, preloaded or hardcoded here.
"""

import os
import threading

from flask import Flask, g, request

import db  # noqa: F401  (in-memory store, imported for its side-effect-free API)
import timeutil  # noqa: F401
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, ApiError
from response import error_response
from services import partner_svc

_lock = threading.RLock()


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    @app.before_request
    def _before_request():
        # Requests are serialised so a multi-step cascade is atomic; the
        # invoice ageing sweep runs before every request because the clock may
        # have moved and because reads must never observe a stale ISSUED row.
        _lock.acquire()
        g._lock_held = True
        partner_svc.sweep_invoices()

    @app.teardown_request
    def _teardown_request(exc):
        if getattr(g, "_lock_held", False):
            g._lock_held = False
            _lock.release()

    from routes import register_routes

    register_routes(app)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _handle_not_found(err):
        return error_response(ERR_NOT_FOUND, "no route matches %s %s" % (request.method, request.path), 404)

    @app.errorhandler(405)
    def _handle_method_not_allowed(err):
        return error_response(
            ERR_NOT_FOUND, "no route matches %s %s" % (request.method, request.path), 404
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):  # pragma: no cover - defensive
        return error_response(ERR_INVALID_REQUEST, "the request could not be processed: %s" % err, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
