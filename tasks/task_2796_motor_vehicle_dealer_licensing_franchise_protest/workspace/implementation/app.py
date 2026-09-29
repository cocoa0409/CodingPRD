"""Motor Vehicle Dealer Board API -- entry point.

The store is entirely in memory and starts EMPTY on every boot: no entity is
seeded, preloaded or hardcoded here or in any module's import-time code. The
harness reboots this process through start.sh before every test, and every
precondition any test needs is built through the declared API surface.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes.applications import bp as applications_bp
from routes.complaints import bp as complaints_bp
from routes.disputes import bp as disputes_bp
from routes.filings import bp as filings_bp
from routes.protests import bp as protests_bp
from routes.reference import bp as reference_bp
from routes.salespersons import bp as salespersons_bp

API_PREFIX = "/dealer-board"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in (
        reference_bp,
        applications_bp,
        salespersons_bp,
        filings_bp,
        protests_bp,
        disputes_bp,
        complaints_bp,
    ):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            return response.error_response("ERR_INVALID_REQUEST", "No such route", 404)
        if status == 405:
            return response.error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)
        if status == 400:
            return response.error_response("ERR_INVALID_REQUEST", "Malformed request", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", error.description or "Request could not be served", status
        )

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return response.error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
