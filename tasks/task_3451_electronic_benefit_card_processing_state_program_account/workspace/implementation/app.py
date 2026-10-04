"""EBT State Benefits API — Flask entry point.

Mounts all business endpoints under /ebt (blueprints) and the logical-clock
endpoint POST /_clock/set_current_utc OUTSIDE the prefix (PRD 2.4).
"""
import os

from flask import Flask
from werkzeug.exceptions import NotFound, MethodNotAllowed, BadRequest

import state
from errors import ApiError
from util import authed, body, req_str, ok_object, error_envelope, parse_iso_dt, iso3
from sweep import run_sweep

app = Flask(__name__)
app.url_map.strict_slashes = False

import contracts
import retailers
import cases
import cards
import authz
import claims
import settlement

for module in (contracts, retailers, cases, cards, authz, claims, settlement):
    app.register_blueprint(module.bp)


@app.post("/_clock/set_current_utc")
def set_current_utc():
    authed(["StateAdmin"])
    b = body()
    raw = req_str(b, "to_iso8601")
    target = parse_iso_dt(raw)
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    now = state.clock_now()
    if target < now:
        raise ApiError("ERR_INVALID_REQUEST", "the logical clock is forward-only")
    run_sweep(now, target)
    state.clock_set(target)
    return ok_object({"current_utc": iso3(state.clock_now())})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_envelope(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(NotFound)
def handle_not_found(exc):
    return error_envelope("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(MethodNotAllowed)
def handle_method_not_allowed(exc):
    return error_envelope("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(BadRequest)
def handle_bad_request(exc):
    return error_envelope("ERR_INVALID_REQUEST", "malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return error_envelope("ERR_INVALID_REQUEST", f"unexpected error: {exc}", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
