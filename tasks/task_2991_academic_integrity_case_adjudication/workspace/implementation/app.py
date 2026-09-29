"""Academic Integrity Case Adjudication API.

A single-process Flask application whose entire state lives in memory and is
therefore empty on every boot: the harness restarts this process before each
test, and nothing is ever seeded, cached on disk or read back from a previous
run.
"""

import json
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_admin
import routes_advisors
import routes_cases
import routes_hearings
import routes_reports
import routes_sanctions
from errors import ApiError
from response import error_body


def json_response(payload, status):
    return json.dumps(payload, allow_nan=False), status, {"Content-Type": "application/json"}


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_reports.bp)
    app.register_blueprint(routes_cases.bp)
    app.register_blueprint(routes_advisors.bp)
    app.register_blueprint(routes_hearings.bp)
    app.register_blueprint(routes_sanctions.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return json_response(error_body(exc.error_id, exc.message), exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_INVALID_REQUEST"
            message = "No such route."
            status = 404
        elif exc.code == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed on this route."
            status = 405
        elif exc.code in (400, 415):
            error_id = "ERR_INVALID_REQUEST"
            message = "The request body could not be read as JSON."
            status = 400
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "Request rejected."
            status = exc.code if exc.code else 400
        return json_response(error_body(error_id, message), status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive only
        payload = error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % (exc,))
        return json_response(payload, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # threaded: a keep-alive connection from one client must never block another.
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
