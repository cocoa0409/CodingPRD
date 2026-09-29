"""Residential Solar Lease / PPA Portfolio Servicing API.

Flask entry point. All state lives in the in-memory store in core.py, which
starts completely empty on every boot: no entity is ever seeded. The only
pre-set value in the whole process is the logical clock's 2026-08-01T00:00:00Z
default, which PRD §2.5 requires.
"""
import os

from flask import Flask

from core import ApiError, clock, fmt_instant, parse_instant
from web import error_response, ok, validate_body

import r_core
import r_periods
import r_trueups
import r_outages
import r_truckrolls
import r_roofwork
import r_transfers
import r_ucc
import r_elections
import r_warranty

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (r_core, r_periods, r_trueups, r_outages, r_truckrolls, r_roofwork,
               r_transfers, r_ucc, r_elections, r_warranty):
    app.register_blueprint(module.bp)


# ---------------------------------------------------------------------------
# PRD §2.5 — the logical clock control endpoint sits outside /servicing and
# outside the authentication rules: headers are not required and are ignored.
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_current_utc():
    body = validate_body([{"name": "current_utc", "kind": "instant",
                           "required": True}])
    clock.set(parse_instant(body["current_utc"]))
    return ok({"current_utc": fmt_instant(clock.now())})


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "No such route.",
                                   http_status=404))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED",
                                   "That method is not allowed on this route.",
                                   http_status=405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", "Unexpected server error: %s"
                                   % err, http_status=500))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
