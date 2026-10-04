"""One-for-One Donation Matching & Giving Partner Distribution API.

Entry point: registers every blueprint, installs the auth/authorization gate and
the two error handlers.  Nothing is seeded here — the store begins empty on
every boot, and every entity is constructed through the declared API surface.
"""

import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from db import DB
from errors import ApiError
from middleware import AUTH_EXEMPT, authenticate, authorize
from response import error
from validation import pagination

from routes.allocations import bp as allocations_bp
from routes.capacity import bp as capacity_bp
from routes.claims import bp as claims_bp
from routes.operator import bp as operator_bp
from routes.partners import bp as partners_bp
from routes.products import bp as products_bp
from routes.sales import bp as sales_bp
from routes.seasons import bp as seasons_bp

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Request gate: authentication (priority 1) then authorization (priority 2)
# ---------------------------------------------------------------------------

def _view_for(request_obj):
    return app.view_functions.get(request_obj.endpoint)


@app.before_request
def gate():
    view = _view_for(request)
    if view is None:
        return None

    # The test-driving controls and the liveness probe live outside the public
    # business surface (PRD section 1), so both the authentication and the
    # authorization rungs are skipped for the whole `/_` namespace.
    exempt = request.path.startswith("/_") or (request.method, request.path) in AUTH_EXEMPT
    if exempt:
        return None

    # Rung 1 — authentication, before any path or body inspection.
    try:
        authenticate()
    except ApiError as exc:
        return error(exc.error_id, exc.message), exc.http_status

    # Rung 2 — authorization.
    allowed = getattr(view, "_allowed_roles", None)
    if allowed is not None:
        try:
            authorize(allowed)
        except ApiError as exc:
            return error(exc.error_id, exc.message), exc.http_status

    # A malformed pagination parameter is an input-shape failure, so it is
    # screened here rather than inside each list handler.
    if "limit" in request.args or "offset" in request.args:
        try:
            pagination()
        except ApiError as exc:
            return error(exc.error_id, exc.message), exc.http_status
    return None


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message), exc.http_status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        error_id = "ERR_INVALID_REQUEST" if exc.code < 500 else "ERR_INVALID_STATE_TRANSITION"
        return error(error_id, exc.description), exc.code
    app.logger.exception("unhandled error")
    return error("ERR_INVALID_REQUEST", str(exc)), 400


for blueprint in (partners_bp, capacity_bp, products_bp, seasons_bp,
                  allocations_bp, sales_bp, claims_bp, operator_bp):
    app.register_blueprint(blueprint)


if __name__ == "__main__":
    DB.reset()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)