"""COE Bundles API -- Employer Direct Contracting / Centers of Excellence.

A single Flask process holding every record in memory. Nothing is seeded and
nothing is persisted: a fresh boot starts with zero rows and a logical clock
reading exactly 2026-09-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.claims import bp as claims_bp
from routes.config import bp as config_bp
from routes.contracts import bp as contracts_bp
from routes.episodes import bp as episodes_bp
from routes.reports import bp as reports_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(episodes_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(reports_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if status == 405:
            return respond_error(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed on this path.",
                405,
            )
        if status in (400, 415):
            return respond_error(
                "ERR_INVALID_REQUEST", exc.description or "Malformed request.", 400
            )
        return respond_error(
            "ERR_INTERNAL", exc.description or "Unhandled error.", status
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover -- defensive
        return respond_error("ERR_INTERNAL", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
