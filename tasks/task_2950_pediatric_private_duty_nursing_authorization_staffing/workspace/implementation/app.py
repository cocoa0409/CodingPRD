"""Pediatric PDN authorization and staffing API -- entry point.

The store is in-memory and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or in any imported module.
"""
import os
import threading

from flask import Flask, g, jsonify

import cascade
import envelope
import routes_cases
import routes_plans
import routes_reference
import routes_shifts
from errors import ApiError

API_PREFIX = "/pdn"

# A single global lock serialises request handling so that concurrent requests can
# never interleave a mutation of the shared in-memory store.
_LOCK = threading.RLock()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_reference.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_plans.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_cases.bp, url_prefix=API_PREFIX)
    app.register_blueprint(routes_shifts.bp, url_prefix=API_PREFIX)

    @app.before_request
    def _before():
        _LOCK.acquire()
        g.pdn_lock_held = True
        cascade.begin()

    @app.teardown_request
    def _teardown(_exc):
        if getattr(g, "pdn_lock_held", False):
            g.pdn_lock_held = False
            try:
                _LOCK.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error("ERR_NOT_FOUND", "The requested path does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return envelope.error(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 405)

    @app.errorhandler(400)
    def _bad_request(_exc):
        return envelope.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error: %s", exc)
        return envelope.error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    @app.route("/healthz", methods=["GET"])
    def _healthz():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
