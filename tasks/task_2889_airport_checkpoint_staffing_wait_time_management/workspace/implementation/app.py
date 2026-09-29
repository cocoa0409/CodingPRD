"""Airport Checkpoint Staffing & Wait-Time Management API.

In-memory Flask application. No persistence, no startup seeding: every entity
is created through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import store
from errors import ApiError
from routes_core import bp as core_bp
from routes_ops import bp as ops_bp
from routes_plans import bp as plans_bp
from routes_staff import bp as staff_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    store.reset()

    app.register_blueprint(core_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return envelope.error("ERR_NOT_FOUND", "the requested resource does not exist", 404)
        if exc.code == 405:
            return envelope.error(
                "ERR_INVALID_REQUEST", "method not allowed for this resource", 400
            )
        if exc.code in (400, 415):
            return envelope.error("ERR_INVALID_REQUEST", "the request could not be parsed", 400)
        return envelope.error(
            "ERR_INTERNAL", exc.description or "unexpected error", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return envelope.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
