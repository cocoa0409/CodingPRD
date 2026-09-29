"""Flask entrypoint for the water-heater manufacturing plant-of-record service.

Storage is in-memory only and always starts empty: a fresh process boots with no
suppliers, no lots, no models and no units, and with the logical clock at its
declared default. The harness relaunches this process before every test, so boot
must be side-effect free.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import assets, clock, models, recalls, suppliers, tanklots, tests, units, warranty

API_PREFIX = "/mfg"

BLUEPRINTS = (
    clock.bp,
    suppliers.bp,
    assets.bp,
    models.bp,
    tanklots.bp,
    tests.bp,
    units.bp,
    warranty.bp,
    recalls.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return (
            response.error_body(
                "ERR_NOT_FOUND", "The requested resource does not exist."
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return (
            response.error_body(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not allowed on this resource.",
            ),
            405,
        )

    @app.errorhandler(400)
    def handle_bad_request(exc):
        # Malformed JSON reaches Flask before any view runs.
        return (
            response.error_body(
                "ERR_INVALID_REQUEST", "The request body could not be parsed as JSON."
            ),
            400,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return (
            response.error_body(
                "ERR_INVALID_REQUEST", exc.description or "The request was rejected."
            ),
            exc.code or 400,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return (
            response.error_body(
                "ERR_INTERNAL", "An unexpected internal error occurred."
            ),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
