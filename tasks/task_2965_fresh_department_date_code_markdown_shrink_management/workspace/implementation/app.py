"""Fresh Department Date-Code, Markdown & Shrink Management API.

Flask entry point: blueprint registration, envelope-shaped error handling and
the foreground server.  Storage is in-memory only and starts completely empty
on every boot -- nothing is seeded, preloaded or hardcoded here.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error
from routes.compliance import bp as compliance_bp
from routes.departments import bp as departments_bp
from routes.donations import bp as donations_bp
from routes.lots import bp as lots_bp
from routes.orders import bp as orders_bp
from routes.registry import bp as registry_bp
from routes.shrink import bp as shrink_bp


class SerialisedMiddleware(object):
    """Serialise requests so multi-step cascades stay atomic."""

    def __init__(self, wsgi_app, lock):
        self._wsgi_app = wsgi_app
        self._lock = lock

    def __call__(self, environ, start_response):
        with self._lock:
            return self._wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in (registry_bp, departments_bp, lots_bp, donations_bp,
                      shrink_bp, compliance_bp, orders_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        status = exc.code or 500
        if status == 404:
            message = "No such route"
        elif status == 405:
            message = "Method not allowed on this route"
        else:
            message = exc.description or "Request could not be processed"
        return error("ERR_INVALID_REQUEST", message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc,
                     500)

    app.wsgi_app = SerialisedMiddleware(app.wsgi_app, db.lock)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
