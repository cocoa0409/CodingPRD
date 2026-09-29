"""Competency-Based Education Direct Assessment Program API.

In-memory only: every collection lives in a Python dict on the ``db``
singleton and is empty at process start.  Nothing is seeded, preloaded or
persisted, so a fresh boot always begins from a blank system whose logical
clock reads 2026-08-01T00:00:00.000Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes.aid import bp as aid_bp
from routes.attempts import bp as attempts_bp
from routes.catalog import bp as catalog_bp
from routes.clock import bp as clock_bp
from routes.integrity import bp as integrity_bp
from routes.mentoring import bp as mentoring_bp
from routes.progress import bp as progress_bp
from routes.students import bp as students_bp
from routes.transcripts import bp as transcripts_bp

BLUEPRINTS = (clock_bp, catalog_bp, students_bp, mentoring_bp, attempts_bp,
              integrity_bp, progress_bp, aid_bp, transcripts_bp)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 400:
            return error_response(
                ApiError("ERR_INVALID_REQUEST", "Malformed request."))
        message = {
            404: "Unknown route.",
            405: "Method not allowed for this route.",
        }.get(exc.code, exc.description or "Request could not be handled.")
        wrapped = ApiError("ERR_INVALID_REQUEST", message)
        wrapped.http_status = exc.code or 400
        return error_response(wrapped)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        wrapped = ApiError("ERR_INVALID_REQUEST", "Unexpected server error.")
        wrapped.http_status = 500
        return error_response(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
