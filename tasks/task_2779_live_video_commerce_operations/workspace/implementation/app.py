"""Live Video Commerce Operations API — entry point.

Storage is entirely in memory and the store starts empty on every boot: no
entity is seeded, preloaded or hardcoded at startup.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError
import routes_a
import routes_bookings
import routes_commerce
import routes_interactions
import routes_merch
import routes_shows


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(routes_a.bp)
    app.register_blueprint(routes_shows.bp)
    app.register_blueprint(routes_bookings.bp)
    app.register_blueprint(routes_merch.bp)
    app.register_blueprint(routes_commerce.bp)
    app.register_blueprint(routes_interactions.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return respond_error(
            "ERR_INVALID_REQUEST", exc.description or "Request could not be served.",
            exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return respond_error("ERR_INVALID_REQUEST", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
