"""Fair Grandstand Entertainment Booking API — Flask application entry point.

Storage is in-memory only and is empty on every boot: the process starts with no
editions, stages, agents, artists, offers, bookings, tiers, advances, sponsors,
activations or settlements, and the logical clock reads 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

from db import REQUEST_LOCK
from errors import ApiError
from response import error_response
from routes.bookings import bp as bookings_bp
from routes.boxoffice import bp as boxoffice_bp
from routes.core import bp as core_bp
from routes.offers import bp as offers_bp
from routes.production import bp as production_bp
from routes.settlements import bp as settlements_bp
from routes.sponsorship import bp as sponsorship_bp

API_PREFIX = "/grandstand"


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in (
        core_bp,
        offers_bp,
        bookings_bp,
        boxoffice_bp,
        production_bp,
        sponsorship_bp,
        settlements_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _serialise_request():
        """One request at a time: every ledger recomputation reads live state."""
        REQUEST_LOCK.acquire()

    @app.teardown_request
    def _release_request(exc=None):
        try:
            REQUEST_LOCK.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error_response("ERR_INVALID_REQUEST", "Request payload failed schema validation.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The HTTP method is not allowed for this resource.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_INTERNAL", str(exc) or "Unhandled server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
