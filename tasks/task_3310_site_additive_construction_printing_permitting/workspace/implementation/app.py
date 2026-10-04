"""Flask entry point: app factory, global auth/idempotency, error handlers."""
import os

from flask import Flask, request, jsonify

from errors import ApiError, raise_err, ERR_UNAUTHENTICATED, ERR_NOT_FOUND
from middleware import get_role, check_idempotency, store_idempotency
from response import error_body

import routes_core
import routes_sites
import routes_plans
import routes_permits
import routes_equipment
import routes_print_jobs
import routes_inspections
import routes_trades

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for bp in (
    routes_core.bp,
    routes_sites.bp,
    routes_plans.bp,
    routes_permits.bp,
    routes_equipment.bp,
    routes_print_jobs.bp,
    routes_inspections.bp,
    routes_trades.bp,
):
    app.register_blueprint(bp)


@app.before_request
def global_guards():
    # Priority 1: X-User-Role presence and recognizability on every endpoint.
    get_role()
    # Priority 2/3: idempotency on all POSTs.
    if request.method == "POST":
        replay = check_idempotency()
        if replay is not None:
            status, body = replay
            resp = jsonify(body)
            resp.status_code = status
            return resp
    return None


@app.after_request
def record_idempotency(response):
    if request.method == "POST" and request.headers.get("Idempotency-Key"):
        if response.status_code < 500:
            try:
                store_idempotency(response.status_code, response.get_json())
            except Exception:
                pass
    return response


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_404(exc):
    body = error_body("ERR_NOT_FOUND", "resource not found")
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(exc):
    body = error_body("ERR_NOT_FOUND", "method not allowed")
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    body = error_body("ERR_INVALID_REQUEST", "malformed request: %s" % exc)
    return jsonify(body), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
