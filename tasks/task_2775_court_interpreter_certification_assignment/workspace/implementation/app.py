"""Court Interpreter Program API — application factory and entry point.

State lives entirely in process memory (see store.py); a fresh process starts
with an empty program and the logical clock at its fixed default.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

import routes_assignments
import routes_calendar
import routes_complaints
import routes_config
import routes_credentials
import routes_payclaims
import routes_reports
import routes_roster

BLUEPRINTS = (
    routes_config.bp,
    routes_roster.bp,
    routes_credentials.bp,
    routes_calendar.bp,
    routes_assignments.bp,
    routes_payclaims.bp,
    routes_complaints.bp,
    routes_reports.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        status = error.code or 500
        if status == 404:
            message = "No such route."
        elif status == 405:
            message = "That method is not allowed on this route."
        else:
            message = error.description or "The request could not be processed."
        return error_response("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def _unhandled(error):
        return error_response("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
