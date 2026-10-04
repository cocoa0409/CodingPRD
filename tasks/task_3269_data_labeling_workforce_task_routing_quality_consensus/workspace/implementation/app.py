"""Entry point for the Data Labeling Ops API.

The store is in-memory and starts empty: nothing here seeds, preloads or
registers any entity. Every entity a caller needs is created through the API
surface itself, so a fresh `python3 app.py` (which is what start.sh hands off
to) is guaranteed to begin from a clean slate.
"""

import os
import sys

from flask import Flask, jsonify

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from envelope import error_response  # noqa: E402
from errors import ERR_INVALID_REQUEST, ERR_UNAUTHORIZED, ApiError  # noqa: E402


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    from routes import register_blueprints

    register_blueprints(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):  # pragma: no cover - exercised through the routes
        return error_response(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error_response(
            ERR_INVALID_REQUEST, "No resource is mounted at this path.", 404
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return error_response(
            ERR_INVALID_REQUEST, "This HTTP method is not admitted on this path.", 405
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.status)
        return error_response(ERR_INVALID_REQUEST, "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)