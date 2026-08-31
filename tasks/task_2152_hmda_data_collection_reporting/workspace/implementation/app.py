"""HMDA Register API -- entry point.

The store is in-memory and starts completely empty on every boot; no entity is
seeded here or anywhere else.
"""

import os
import sys
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error_response  # noqa: E402

from routes.institutions import bp as institutions_bp  # noqa: E402
from routes.census_tracts import bp as census_tracts_bp  # noqa: E402
from routes.applications import bp as applications_bp  # noqa: E402
from routes.demographics import bp as demographics_bp  # noqa: E402
from routes.geocodes import bp as geocodes_bp  # noqa: E402
from routes.editruns import bp as editruns_bp  # noqa: E402
from routes.submissions import bp as submissions_bp  # noqa: E402
from routes.audits import bp as audits_bp  # noqa: E402
from routes.fairlending import bp as fairlending_bp  # noqa: E402
from routes.clock import bp as clock_bp  # noqa: E402


class SerializingMiddleware(object):
    """Each request runs to completion before the next one starts.

    Multi-step operations (edit runs, the reopen cascade, filing) must be
    atomic, and optimistic concurrency has to see a stable parent version.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
        self.lock = threading.RLock()

    def __call__(self, environ, start_response):
        with self.lock:
            result = self.wsgi_app(environ, start_response)
            try:
                return list(result)
            finally:
                close = getattr(result, "close", None)
                if close is not None:
                    close()


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (institutions_bp, census_tracts_bp, applications_bp,
                      demographics_bp, geocodes_bp, editruns_bp, submissions_bp,
                      audits_bp, fairlending_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
