"""Newsroom Standards & Corrections API.

Flask application factory and process entry point.  All state lives in
process-local memory (see store.py) and the store starts empty on every boot:
nothing is seeded, preloaded or hardcoded.
"""

import os
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import respond_error
from errors import ApiError
from routes import assignments, conflicts, corrections, misconduct, reviews, sources, setup, stories

API_PREFIX = "/standards-desk"

BLUEPRINTS = (
    setup.bp,
    stories.bp,
    sources.bp,
    reviews.bp,
    assignments.bp,
    corrections.bp,
    misconduct.bp,
    conflicts.bp,
)


class LockMiddleware(object):
    """Serialize request handling so the in-memory aggregates stay consistent
    even when the harness fires concurrent requests."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.Lock()

    def __call__(self, environ, start_response):
        with self.lock:
            result = self.wsgi_app(environ, start_response)
            # Materialize the iterable inside the lock; Flask returns a list.
            return list(result)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST",
                                 "The method is not allowed for this route.", 405)
        if exc.code in (400, 415):
            return respond_error("ERR_INVALID_REQUEST", "The request is malformed.", 400)
        return respond_error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                             exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover
        return respond_error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    app.wsgi_app = LockMiddleware(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False, debug=False)
