"""Retina practice intravitreal-injection buy-and-bill API.

Storage is in-memory only: every process start begins with an empty world and
nothing is ever seeded. Run with `bash start.sh` (PORT defaults to 10000).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import _meta
import routes_authorizations
import routes_billing
import routes_clinical
import routes_encounters
import routes_inventory
import routes_reference
import routes_safety


def envelope_error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_clinical.bp)
    app.register_blueprint(routes_inventory.bp)
    app.register_blueprint(routes_authorizations.bp)
    app.register_blueprint(routes_encounters.bp)
    app.register_blueprint(routes_billing.bp)
    app.register_blueprint(routes_safety.bp)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return envelope_error("ERR_INVALID_REQUEST", "unknown resource path", 404)
        if exc.code == 405:
            return envelope_error("ERR_INVALID_REQUEST", "method not allowed", 405)
        return envelope_error(
            "ERR_INVALID_REQUEST", exc.description or "bad request", exc.code or 400
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return envelope_error("ERR_INVALID_REQUEST", "unhandled server error: %r" % (exc,), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
