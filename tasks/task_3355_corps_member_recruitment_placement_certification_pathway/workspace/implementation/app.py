"""Corps Recruitment, Placement & Certification API — Flask entry point.

The store is in-memory only and starts empty on every boot; nothing is seeded,
preloaded or registered at startup. Every per-test reboot through start.sh
therefore begins from a clean slate.
"""

import os
import sys
import traceback

from flask import Flask

import services
from envelope import error_body
from errors import ApiError

import routes_cert
import routes_core
import routes_members
import routes_misc
import routes_placements
import routes_selection

app = Flask(__name__)

for module in (
    routes_core,
    routes_selection,
    routes_cert,
    routes_members,
    routes_placements,
    routes_misc,
):
    app.register_blueprint(module.bp)


@app.before_request
def _apply_clock_effects():
    """The two clock-driven system transitions (placement completion at term end,
    district agreement expiry at term start) are applied lazily before every
    request, so a clock advance is observable on the next read."""
    services.settle_clock_effects()


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _handle_not_found(_exc):
    return error_body(
        "ERR_INVALID_REQUEST", "The requested path does not correspond to any operation.", 404
    )


@app.errorhandler(405)
def _handle_method_not_allowed(_exc):
    return error_body(
        "ERR_INVALID_REQUEST", "The requested method is not allowed on this path.", 405
    )


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    return error_body("ERR_INVALID_REQUEST", "The request could not be processed.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
