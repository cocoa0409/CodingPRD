"""Hybrid Work Policy & Attendance Compliance API - entry point."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (attendance, cycles, employees, escalation, exceptions,
                    recalibration, relocation, space)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(cycles.bp)
    app.register_blueprint(employees.bp)
    app.register_blueprint(attendance.bp)
    app.register_blueprint(exceptions.bp)
    app.register_blueprint(relocation.bp)
    app.register_blueprint(space.bp)
    app.register_blueprint(escalation.bp)
    app.register_blueprint(recalibration.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return response.error_response("ERR_INVALID_REQUEST", "unknown route", 404)
        if error.code == 405:
            return response.error_response("ERR_INVALID_REQUEST",
                                           "method not allowed for this route", 405)
        return response.error_response("ERR_INVALID_REQUEST",
                                       error.description or "bad request",
                                       error.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(error):
        return response.error_response("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
