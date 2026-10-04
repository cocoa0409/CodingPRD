"""App entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_response

import routes_productions
import routes_assets
import routes_batches
import routes_shows
import routes_bookings
import routes_venue_systems
import routes_sponsors
import routes_clock


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_productions.bp)
    app.register_blueprint(routes_assets.bp)
    app.register_blueprint(routes_batches.bp)
    app.register_blueprint(routes_shows.bp)
    app.register_blueprint(routes_bookings.bp)
    app.register_blueprint(routes_venue_systems.bp)
    app.register_blueprint(routes_sponsors.bp)
    app.register_blueprint(routes_clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", "Internal error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
