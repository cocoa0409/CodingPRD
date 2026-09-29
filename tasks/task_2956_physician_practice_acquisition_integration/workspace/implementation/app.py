"""Practice Acquisition Integration API.

Flask application factory and entry point.  All state lives in plain in-memory
dicts (see store.py); nothing is persisted, seeded or preloaded, so relaunching
this process yields a completely empty system.
"""

import decimal
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_acquisitions
import routes_billing
import routes_comp_plans
import routes_credentialing
import routes_liability
import routes_migration
import routes_payers
import routes_performance
import routes_physicians
import routes_readiness
import routes_reads
import routes_staff
import routes_valuations
from errors import ApiError

# Wide precision for the exact-decimal money and rate arithmetic.  Setting it on
# DefaultContext as well means every Flask worker thread inherits it.
decimal.DefaultContext.prec = 60
decimal.setcontext(decimal.DefaultContext)
decimal.getcontext().prec = 60

ROUTE_MODULES = (
    routes_reads,
    routes_acquisitions,
    routes_physicians,
    routes_valuations,
    routes_comp_plans,
    routes_payers,
    routes_credentialing,
    routes_migration,
    routes_staff,
    routes_billing,
    routes_readiness,
    routes_liability,
    routes_performance,
)


def create_app():
    app = Flask(__name__)
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for module in ROUTE_MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message,
                                      exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 400:
            return envelope.error_response(
                "ERR_INVALID_REQUEST", "The request could not be understood.", 400)
        if exc.code in (404, 405):
            return envelope.error_response(
                "ERR_RESOURCE_NOT_FOUND",
                "The requested resource does not exist.", 404)
        if exc.code == 401:
            return envelope.error_response(
                "ERR_UNAUTHENTICATED", "Authentication is required.", 401)
        if exc.code == 403:
            return envelope.error_response(
                "ERR_FORBIDDEN_ROLE", "This role is not authorised.", 403)
        return envelope.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Request failed",
            exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return envelope.error_response("ERR_INTERNAL", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
