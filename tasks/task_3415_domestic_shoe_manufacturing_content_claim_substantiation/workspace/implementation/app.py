"""Application factory and entry point.

Registers every route blueprint and renders ApiError (and any framework or
unexpected failure) in the standard error envelope. Binds 0.0.0.0:$PORT
(default 10000) in the foreground.
"""
import os
import traceback

from flask import Flask

from errors import ApiError
from response import error_response

import routes_capacity
import routes_claims
import routes_clock
import routes_evidence
import routes_factories
import routes_gov
import routes_lots
import routes_models
import routes_orders
import routes_reports
import routes_runs
import routes_runs_lifecycle
import routes_workforce

_BLUEPRINTS = (
    routes_clock.bp,
    routes_factories.bp,
    routes_models.bp,
    routes_lots.bp,
    routes_runs.bp,
    routes_runs_lifecycle.bp,
    routes_reports.bp,
    routes_orders.bp,
    routes_claims.bp,
    routes_evidence.bp,
    routes_workforce.bp,
    routes_capacity.bp,
    routes_gov.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for bp in _BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)

    @app.errorhandler(Exception)
    def _internal(e):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
