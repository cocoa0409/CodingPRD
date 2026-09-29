"""Orthopedic In-Office DME Dispensing API.

Storage is in-memory only and starts completely empty on every boot: no seeding,
no preloading, no persistence of any kind. The harness relaunches this process
before every individual test, so a fresh boot must always be a clean slate.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from common import ApiError, respond_error
from routes import (catalog, clinics, clock, encounters, fabrication, finance,
                    inventory, returns)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (clock, clinics, catalog, inventory, encounters, finance,
                   fabrication, returns):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error("ERR_NOT_FOUND", "No such route.", 404)
        if status == 405:
            return respond_error("ERR_METHOD_NOT_ALLOWED",
                                 "The method is not allowed for this route.", 405)
        if status == 400:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The request could not be parsed.", 400)
        return respond_error("ERR_INTERNAL", exc.description or "Request failed.",
                             status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return respond_error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
