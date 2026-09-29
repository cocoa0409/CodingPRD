"""Extended School Year & Compensatory Services API.

A single Flask process holding all state in memory (see store.py). Nothing is
persisted and nothing is seeded: every record is created through the API.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (assignments, awards, clock, commitments, determinations,
                    due_process, fund_allocations, makeup, programs, providers,
                    service_logs, students, transportation)

BLUEPRINTS = (
    clock.bp,
    students.bp,
    determinations.bp,
    programs.bp,
    providers.bp,
    fund_allocations.bp,
    transportation.bp,
    commitments.bp,
    assignments.bp,
    service_logs.bp,
    awards.bp,
    makeup.bp,
    due_process.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_missing_route(exc):
        return error_response("ERR_NOT_FOUND", "The requested route does not exist.",
                              404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request body could not be parsed.", 422)
        return error_response("ERR_HTTP_ERROR", exc.description or "HTTP error",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        app.logger.exception("unhandled error: %s", exc)
        return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
