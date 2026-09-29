"""Medical Professional Liability API - Flask application factory and entrypoint.

State lives only in process memory (see store.py): every boot starts empty and
no entity data is ever seeded.
"""
import os

from flask import Flask, g

from envelope import error_response
from errors import ApiError

from routes import analytics, claims, clock, counsel, insureds, negotiations
from routes import npdb, policies, rate_manual


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        rate_manual,
        insureds,
        policies,
        claims,
        counsel,
        negotiations,
        npdb,
        analytics,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _reset_unit_of_work():
        g._dirty = {}
        g._fresh = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response(
            "ERR_NOT_FOUND", "The requested resource does not exist.", 404
        )

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this route.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
