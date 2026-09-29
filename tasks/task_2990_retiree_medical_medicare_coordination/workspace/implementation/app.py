"""Retiree Medical & Medicare Coordination API.

All state lives in process memory (see store.py) and is discarded when the
process exits, so every boot starts from a completely empty programme.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_claims
import routes_determinations
import routes_elections
import routes_enrollments
import routes_hra
import routes_invoices
import routes_ops
import routes_plan_options
import routes_plan_years
import routes_retirees
from envelope import error_response
from errors import ApiError

BLUEPRINTS = (
    routes_plan_years.bp,
    routes_retirees.bp,
    routes_plan_options.bp,
    routes_determinations.bp,
    routes_elections.bp,
    routes_enrollments.bp,
    routes_hra.bp,
    routes_claims.bp,
    routes_invoices.bp,
    routes_ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_RESOURCE_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif status < 500:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INTERNAL"
        return error_response(error_id, error.description or error.name, status)

    @app.errorhandler(Exception)
    def _handle_unexpected(error):
        return error_response("ERR_INTERNAL", str(error) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
