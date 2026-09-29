"""Guest Ranch All-Inclusive Resort Operations API — application entry point.

State lives entirely in memory: every launch of this process starts from an
empty ranch with the logical clock at the mandated 2026-08-01T00:00:00Z default.
Nothing is seeded, cached on disk or read back from a previous run.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
import routes_bookings
import routes_guests
import routes_horses
import routes_incidents
import routes_reservations
import routes_seasons
import routes_slots
import routes_staff

BLUEPRINTS = (
    routes_seasons.bp,
    routes_guests.bp,
    routes_bookings.bp,
    routes_horses.bp,
    routes_slots.bp,
    routes_reservations.bp,
    routes_staff.bp,
    routes_incidents.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return error_response(
                ApiError("ERR_INVALID_FIELD_VALUE", "No such route.", 404)
            )
        if err.code == 405:
            return error_response(
                ApiError("ERR_INVALID_FIELD_VALUE", "Method not allowed.", 405)
            )
        return error_response(
            ApiError("ERR_INVALID_FIELD_VALUE", err.description or "Bad request", err.code)
        )

    @app.errorhandler(Exception)
    def _unhandled(err):
        return error_response(
            ApiError("ERR_INVALID_FIELD_VALUE", "Unhandled server error: %s" % err, 500)
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
