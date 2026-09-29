"""Rail Interchange & Car Hire Accounting -- Flask entry point.

The process starts with an entirely empty in-memory store: no railroads, no
cars, no cycles.  Every row is created through the declared endpoints.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, message_for
from routes import cars, config, corrections, cycles, events, reclaim, repair


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(config.bp)
    app.register_blueprint(cars.bp)
    app.register_blueprint(events.bp)
    app.register_blueprint(reclaim.bp)
    app.register_blueprint(repair.bp)
    app.register_blueprint(cycles.bp)
    app.register_blueprint(corrections.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response(
            "ERR_NOT_FOUND", "No resource is mounted at that path.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", "That method is not allowed on this path.", 405
        )

    @app.errorhandler(400)
    def _bad_request(_exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", message_for("ERR_INVALID_REQUEST"), 400
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code or 400
        )

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return response.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
