"""Home Battery Storage API -- Flask application factory and entry point.

State lives in process memory only (see store.py), so every fresh launch of this
module starts from an empty world with the logical clock at its epoch.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import ApiError
from routes.alerts import bp as alerts_bp
from routes.byod import bp as byod_bp
from routes.core import bp as core_bp
from routes.incentives import bp as incentives_bp
from routes.interconnection import bp as interconnection_bp
from routes.loadcalc import bp as loadcalc_bp
from routes.permits import bp as permits_bp
from routes.systems import bp as systems_bp
from routes.tests import bp as tests_bp

BLUEPRINTS = (
    core_bp,
    loadcalc_bp,
    systems_bp,
    permits_bp,
    interconnection_bp,
    incentives_bp,
    tests_bp,
    alerts_bp,
    byod_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _domain_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def _bad_request(exc):
        return error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def _not_found(exc):
        return error("ERR_INVALID_REQUEST", "No such endpoint.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error("ERR_INVALID_REQUEST", exc.description or "Request rejected.", exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
