"""Flask application entry point."""

import os

from flask import Flask, request

from db import clock
from errors import ApiError, err_invalid_request, err_unauthenticated
from helpers import run_sweeps
from middleware import get_identity, require_role, resolve_identity
from response import error_response, success_object, parse_iso, iso_no_frac

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


@app.post("/licensing/_clock/set_current_utc")
def set_clock():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    if payload is None or "to_iso8601" not in payload or payload["to_iso8601"] is None:
        raise err_invalid_request("Missing required field: to_iso8601")
    try:
        target = parse_iso(payload["to_iso8601"])
    except Exception:
        raise err_invalid_request("to_iso8601 must be ISO8601")
    clock["current"] = iso_no_frac(target)
    run_sweeps()
    return success_object({"current_utc": clock["current"]})


from routes_orgs import bp as orgs_bp
from routes_plans import bp as plans_bp
from routes_subscriptions import bp as subs_bp
from routes_transfers import bp as transfers_bp
from routes_addons import bp as addons_bp
from routes_billing import bp as billing_bp

app.register_blueprint(orgs_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(subs_bp)
app.register_blueprint(transfers_bp)
app.register_blueprint(addons_bp)
app.register_blueprint(billing_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
