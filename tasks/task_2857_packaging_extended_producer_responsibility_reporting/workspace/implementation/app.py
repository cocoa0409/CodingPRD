"""Packaging EPR Reporting API — application entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (engagements, invoices, memberships, misc, producers,
                    programs, pros, registrations, reports, skus)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for module in (
        producers,
        skus,
        programs,
        pros,
        registrations,
        memberships,
        reports,
        engagements,
        invoices,
        misc,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response(
                "ERR_INVALID_REQUEST", "The method is not allowed for this path.", 405
            )
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return error_response(
            "ERR_INVALID_REQUEST", exc.description or "The request could not be processed.", exc.code
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
