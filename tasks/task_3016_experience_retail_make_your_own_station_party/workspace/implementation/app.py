"""Experience Retail Workshop API.

A single Flask process holding every record in memory. Nothing is seeded and
nothing is persisted: a fresh boot starts with zero rows and a logical clock
reading exactly 2026-09-01T00:00:00Z (PRD section 2.4).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.admin import bp as admin_bp
from routes.workshops import bp as workshops_bp
from routes.parties import bp as parties_bp
from routes.commerce import bp as commerce_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(admin_bp)
    app.register_blueprint(workshops_bp)
    app.register_blueprint(parties_bp)
    app.register_blueprint(commerce_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status in (404, 405):
            return respond_error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if status in (400, 415):
            return respond_error(
                "ERR_VALIDATION", exc.description or "Malformed request.", 422
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
