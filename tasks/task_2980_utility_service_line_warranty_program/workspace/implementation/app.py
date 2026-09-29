"""Utility Service Line Warranty Program API.

A single Flask process holding the entire programme in memory.  Nothing is
persisted anywhere: a fresh boot starts with no partners, no policies and no
ledger, and every entity a caller needs is created through the declared
endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import config
from errors import ApiError
from response import error_response
from routes import (
    campaigns,
    claims,
    complaints,
    contractors,
    dispatches,
    enrollments,
    ledger,
    operations,
    partners,
    premises,
    products,
)
from validation import current_role, current_user_id

BLUEPRINTS = (
    partners.bp,
    products.bp,
    premises.bp,
    campaigns.bp,
    enrollments.bp,
    claims.bp,
    contractors.bp,
    dispatches.bp,
    ledger.bp,
    complaints.bp,
    operations.bp,
)


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    @app.before_request
    def authenticate():
        """Authentication outranks everything, including URL resolution."""
        current_user_id()
        role = current_role()
        if role not in config.ALL_ROLES:
            raise ApiError("ERR_UNAUTHORIZED", "Role %r is not admitted to this API" % role)
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return error_response("ERR_INVALID_REQUEST", "No such endpoint", 404)
        if exc.code == 405:
            return error_response("ERR_INVALID_REQUEST", "Method not allowed on this path", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "The request could not be parsed", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request refused", exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive only
        return error_response("ERR_INVALID_REQUEST", "Unhandled server condition: %s" % exc, 500)

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
