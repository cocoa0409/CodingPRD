"""Education Savings Account Administration API (PRD /esa mount).

Boots completely empty on every process start: no entity data is seeded,
preloaded or hardcoded anywhere.  All state lives in process memory.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes import (accounts, appeals, applications, misuse_cases,
                    program_years, providers, purchase_requests,
                    renewal_reviews, students)
from store import lock

API_PREFIX = "/esa"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (program_years, students, applications, providers,
                   accounts, purchase_requests, misuse_cases,
                   renewal_reviews, appeals):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    # One writer at a time: every request mutates a shared in-memory graph.
    @app.before_request
    def _acquire():
        lock.acquire()

    @app.teardown_request
    def _release(exc=None):
        try:
            lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST",
                                  "no such endpoint", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST",
                                  "method not allowed for this endpoint", 405)
        if exc.code and exc.code < 500:
            return error_response("ERR_INVALID_REQUEST",
                                  exc.description or "malformed request", 400)
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "server error", exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error_response("ERR_INVALID_REQUEST",
                              "unexpected server error: %s" % exc, 500)

    return app


application = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True,
                    debug=False, use_reloader=False)
