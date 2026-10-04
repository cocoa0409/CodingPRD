"""Org Platform Admin API — application entry point.

Boots a fresh, empty in-memory store on every process start (nothing is seeded
or preloaded), which is what makes the per-test-server isolation model safe: a
``start.sh`` re-invocation wipes all state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db  # noqa: F401  (imported so the empty store is initialised per boot)
from errors import ApiError
from routes import (
    access_audits,
    change_sets,
    environments,
    governor_requests,
    installed_packages,
    package_versions,
    refresh_jobs,
    storage_ledgers,
    test_driving,
)

BLUEPRINTS = (
    environments.bp,
    refresh_jobs.bp,
    package_versions.bp,
    installed_packages.bp,
    change_sets.bp,
    governor_requests.bp,
    storage_ledgers.bp,
    access_audits.bp,
    test_driving.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return _envelope(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_error(exc):
        return _envelope(
            "ERR_RESOURCE_NOT_FOUND" if exc.code == 404 else "ERR_INVALID_REQUEST",
            exc.description or exc.name,
            exc.code,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        from werkzeug.exceptions import HTTPException as WerkzeugHTTPException
        import traceback

        if isinstance(exc, WerkzeugHTTPException):
            return _handle_http_error(exc)
        traceback.print_exc()
        return _envelope("ERR_INVALID_REQUEST", str(exc), 500)

    return app


def _envelope(error_id, message, status):
    from response import error_body

    return error_body(error_id, message, status)


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))