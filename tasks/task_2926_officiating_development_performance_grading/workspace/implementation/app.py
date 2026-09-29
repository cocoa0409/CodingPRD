"""Officiating Development & Grading API -- Flask application entry point.

Storage is entirely in memory (see db.py) and nothing is seeded: every entity is
created through a declared endpoint. The logical clock starts at exactly
2026-08-01T00:00:00.000Z on every boot.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from errors import ApiError
from response import error_response
from routes import (appeals, applications, assignments, clock, discipline,
                    games, officials, play_grades, pool_reports, replay,
                    season_programs)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for module in (clock, season_programs, officials, applications, games,
                   assignments, play_grades, appeals, replay, pool_reports,
                   discipline):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            message = "The requested resource does not exist."
        elif status == 405:
            message = "The HTTP method is not allowed for this path."
        else:
            message = exc.description or "The request could not be processed."
        return error_response(errors.ERR_INVALID_REQUEST, message, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response(errors.ERR_INVALID_REQUEST,
                              "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
