"""Public Records Data Journalism Desk API.

A single Flask process holding all state in memory.  Nothing is persisted and
nothing is ever seeded: every boot starts with fourteen empty collections and a
logical clock reading 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (analysis_runs, appeals, clock_routes, datasets, desks,
                    enclaves, findings, investigations, records_requests,
                    reviewers, subjects)

API_PREFIX = "/records-desk"

DOMAIN_BLUEPRINTS = (
    desks.bp,
    records_requests.bp,
    appeals.bp,
    datasets.bp,
    investigations.bp,
    analysis_runs.bp,
    findings.bp,
    reviewers.bp,
    subjects.bp,
    enclaves.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    try:
        app.json.sort_keys = False
    except Exception:  # pragma: no cover - older Flask
        pass

    for blueprint in DOMAIN_BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    # The logical clock lives outside the /records-desk prefix.
    app.register_blueprint(clock_routes.bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc):
        status = exc.code or 500
        if status == 404:
            return response.error_response(
                "ERR_INVALID_REQUEST", "No such resource on this server.", 404)
        if status == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "That method is not allowed on this resource.", 405)
        if status == 400:
            return response.error_response(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed.", status)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover - defensive
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
