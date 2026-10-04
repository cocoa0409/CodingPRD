"""Digital Freight Matching API — entry point.

In-memory only: the store starts empty on every boot and nothing is persisted.
"""

import os
import sys
from datetime import date, datetime

from flask import Flask, request
from flask.json.provider import DefaultJSONProvider

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import fmt  # noqa: E402
from errors import ApiError  # noqa: E402
from middleware import authenticate  # noqa: E402
from response import error_response  # noqa: E402
from routes import register_routes  # noqa: E402


class IsoJsonProvider(DefaultJSONProvider):
    """Every datetime leaves as ISO 8601 UTC with three fractional digits."""

    @staticmethod
    def default(obj):
        if isinstance(obj, datetime):
            return fmt(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json = IsoJsonProvider(app)
    app.json.sort_keys = False

    @app.before_request
    def _authenticate_first():
        """Priority 1 runs before every other check, including existence."""
        if request.path.startswith("/v1"):
            authenticate()
        return None

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error)

    @app.errorhandler(404)
    def _not_found(error):
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", "No such operation exists on this platform."))

    @app.errorhandler(405)
    def _method_not_allowed(error):
        return error_response(ApiError(
            "ERR_INVALID_REQUEST", "That method is not supported on this path."))

    @app.errorhandler(Exception)
    def _unexpected(error):
        if isinstance(error, ApiError):
            return error_response(error)
        return error_response(ApiError("ERR_INVALID_REQUEST",
                                       "The request could not be processed."))

    register_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)