"""Wind Farm Operations & Turbine Maintenance API."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, DEFAULT_MESSAGES

from routes.setup import bp as setup_bp
from routes.control import bp as control_bp
from routes.planning import bp as planning_bp
from routes.major import bp as major_bp
from routes.commercial import bp as commercial_bp

BASE = "/wind-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (setup_bp, control_bp, planning_bp, major_bp, commercial_bp):
        app.register_blueprint(blueprint, url_prefix=BASE)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_PATH_RESOURCE_NOT_FOUND", DEFAULT_MESSAGES["ERR_PATH_RESOURCE_NOT_FOUND"]
            )
        if exc.code == 405:
            return error_response(
                "ERR_PATH_RESOURCE_NOT_FOUND", "Method not allowed for this path."
            )
        if exc.code in (400, 411, 413, 415, 422):
            return error_response("ERR_INVALID_REQUEST", "The request is malformed.")
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.")

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
