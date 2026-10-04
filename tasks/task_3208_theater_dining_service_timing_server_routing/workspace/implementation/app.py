"""HTTP entry point for the theater dining service.

The world starts empty on every process boot: nothing is seeded, preloaded or
registered at import time. All state lives in process memory (see db.py), so a
fresh `bash start.sh` invocation wipes every byte of it.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response as envelope
from errors import ApiError
from routes import auditoriums as auditorium_routes
from routes import clock as clock_routes
from routes import orders as order_routes
from routes import programming as programming_routes
from routes import servers as server_routes
from routes import showtimes as showtime_routes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(auditorium_routes.bp)
    app.register_blueprint(showtime_routes.bp)
    app.register_blueprint(programming_routes.bp)
    app.register_blueprint(server_routes.bp)
    app.register_blueprint(order_routes.bp)
    app.register_blueprint(clock_routes.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return envelope.error_body(errors.ERR_SHOWTIME_NOT_FOUND,
                                   "No route matches the requested path."), 404

    @app.errorhandler(405)
    def handle_method(_exc):
        return envelope.error_body(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                                   "Method not allowed on this path."), 405

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        body = envelope.error_body(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                                   exc.description or exc.name)
        return body, exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error_body(exc.error_id, exc.message), exc.http_status
        body = envelope.error_body(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                                   str(exc))
        return body, 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False,
            threaded=True)