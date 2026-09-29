"""Venue Music Licensing API -- application factory and entry point.

State lives in plain Python dicts inside `db.py`; nothing is persisted and
nothing is seeded, so a fresh process always starts empty (PRD 2.4, 2.5).
"""

import logging
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_applications
import routes_audit
import routes_licenses
import routes_reference
import routes_reports

HTTP_STATUS_ERRORS = {
    400: "ERR_INVALID_REQUEST",
    404: "ERR_INVALID_REQUEST",
    405: "ERR_INVALID_REQUEST",
    415: "ERR_INVALID_REQUEST",
}


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_reference.bp)
    app.register_blueprint(routes_applications.bp)
    app.register_blueprint(routes_licenses.bp)
    app.register_blueprint(routes_reports.bp)
    app.register_blueprint(routes_audit.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return respond_error(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        error_id = HTTP_STATUS_ERRORS.get(error.code, "ERR_INVALID_REQUEST")
        return respond_error(error_id, error.description or error.name, error.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(error):
        return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
