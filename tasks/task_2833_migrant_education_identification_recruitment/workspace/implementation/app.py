"""Migrant Education Identification & Recruitment API.

Flask application factory and process entry point.  All state is held in
process memory (see store.py) and is therefore empty on every boot: nothing is
seeded, preloaded or persisted to disk.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_areas
import routes_coes
import routes_services
import routes_students
import routes_terms
from envelope import error
from errors import ERROR_CATALOG, ApiError
from store import store


class _Serialized(object):
    """Serialises requests so multi-hop cascades are never interleaved."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with store.lock:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(routes_areas.bp)
    app.register_blueprint(routes_students.bp)
    app.register_blueprint(routes_coes.bp)
    app.register_blueprint(routes_terms.bp)
    app.register_blueprint(routes_services.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        code = exc.code or 500
        if code == 404:
            return error("ERR_NOT_FOUND", "The requested path does not exist", 404)
        if code == 405:
            return error(
                "ERR_METHOD_NOT_ALLOWED",
                "The HTTP method is not supported for this path",
                405,
            )
        if code == 400:
            return error("ERR_INVALID_REQUEST", "The request could not be parsed", 422)
        return error("ERR_INVALID_REQUEST", exc.description or "Request failed", code)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover -- defensive
        return error("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    app.wsgi_app = _Serialized(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
