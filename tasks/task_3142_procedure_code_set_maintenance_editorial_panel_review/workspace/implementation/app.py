"""Application entry point.

Registers every route module, installs the catalogued error handling and runs
the server on `0.0.0.0:$PORT`.  No entity data is seeded here or anywhere else:
the store starts empty on every fresh process and every record any request
touches is created through a declared endpoint.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import auth
from errors import ERR_INVALID_STATE, ERR_NOT_FOUND, ApiError
from response import error_response
from routes import (
    changes,
    clock_routes,
    code_values,
    comments,
    committee,
    delivery,
    errata,
    licensing,
    meetings,
    release,
    societies,
    valuation,
    votes,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for module in (
        societies,
        changes,
        committee,
        meetings,
        comments,
        votes,
        valuation,
        code_values,
        release,
        errata,
        licensing,
        delivery,
        clock_routes,
    ):
        app.register_blueprint(module.bp, url_prefix="/cpt")

    install_error_handlers(app)
    return app


def install_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        # An unknown path or an undeclared method is not part of the declared
        # surface, so it resolves to the not-found identifier.  The identity
        # gate still runs first: a request that omits its headers is rejected
        # before anything else, exactly as on a declared endpoint.
        if exc.code in (404, 405):
            failure = _identity_gate_failure()
            if failure is not None:
                return error_response(failure[0], failure[1], failure[2])
            return error_response(ERR_NOT_FOUND, "the requested resource was not found")
        return error_response(ERR_NOT_FOUND, exc.description or "request failed")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return error_response(ERR_INVALID_STATE, "the request could not be completed")


def _identity_gate_failure():
    """Return (error_id, message, status) when the identity gate would fail."""
    try:
        auth.authenticate(request.headers)
    except ApiError as exc:
        return (exc.error_id, exc.message, exc.http_status)
    return None


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)