"""Child Support Enforcement API — application entry point.

Storage is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded here or in any imported module.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (cases, charges, clock, compromise, employers, enforcement,
                    interstate, iwo, orders, participants, paternity, reviews)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (clock, participants, cases, paternity, orders, employers,
                   iwo, charges, reviews, enforcement, interstate, compromise):
        module.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error("ERR_NOT_FOUND", "The requested route does not exist.",
                              404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 404:
            return handle_not_found(exc)
        if exc.code == 405:
            return handle_method_not_allowed(exc)
        if exc.code == 400:
            # A malformed JSON body is a payload-shape violation.
            return response.error("ERR_VALIDATION",
                                  "The request body is not valid JSON.", 422)
        return response.error("ERR_INTERNAL", exc.description or "Internal error.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
