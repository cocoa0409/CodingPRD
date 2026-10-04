"""Piano Manufacturing Bank API — Flask entry point.

In-memory only; every boot starts from empty state. Reads $PORT (default
10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask

import envelope
from errors import ApiError
from routes_artists import bp as artists_bp
from routes_builds import bp as builds_bp
from routes_clock import bp as clock_bp
from routes_endorse import bp as endorse_bp
from routes_instruments import bp as instruments_bp
from routes_loans import bp as loans_bp
from routes_people import bp as people_bp
from routes_restore import bp as restore_bp
from routes_wood import bp as wood_bp


def create_app():
    app = Flask(__name__)
    for bp in (
        wood_bp,
        builds_bp,
        people_bp,
        endorse_bp,
        instruments_bp,
        artists_bp,
        loans_bp,
        restore_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return envelope.err("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return envelope.err("ERR_NOT_FOUND", 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return envelope.err(e.error_id, e.http_status, e.message)
        return envelope.err("ERR_INTERNAL", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True, use_reloader=False)
