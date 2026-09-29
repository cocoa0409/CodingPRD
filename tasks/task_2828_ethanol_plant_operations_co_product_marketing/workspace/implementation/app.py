"""Ethanol Plant Operations & Co-Product Marketing API.

Storage is in-memory only and nothing is seeded: every dict starts empty on
each boot and all state vanishes when the process exits.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import bp
import routes.plant  # noqa: F401
import routes.corn  # noqa: F401
import routes.ferment  # noqa: F401
import routes.tanks  # noqa: F401
import routes.rail  # noqa: F401
import routes.sales  # noqa: F401
import routes.rins  # noqa: F401
import routes.carbon  # noqa: F401
import routes.hedge  # noqa: F401
import routes.permits  # noqa: F401


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_VALIDATION", "Unknown route", 404)
        if exc.code == 405:
            return error_response("ERR_VALIDATION", "Method not allowed", 405)
        return error_response("ERR_VALIDATION", exc.description or "Bad request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "Unhandled error: %s" % exc, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
