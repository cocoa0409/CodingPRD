"""Entry point: error handlers and blueprint registration."""

import os
import signal
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error

from routes.communities import bp as communities_bp
from routes.commitments import bp as commitments_bp
from routes.home_sites import bp as home_sites_bp
from routes.buyers import bp as buyers_bp
from routes.contracts import bp as contracts_bp
from routes.applications import bp as applications_bp
from routes.rate_locks import bp as rate_locks_bp
from routes.allocations import bp as allocations_bp
from routes.buydowns import bp as buydowns_bp
from routes.disclosures import bp as disclosures_bp
from routes.forfeitures import bp as forfeitures_bp
from routes.clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (
    communities_bp,
    commitments_bp,
    home_sites_bp,
    buyers_bp,
    contracts_bp,
    applications_bp,
    rate_locks_bp,
    allocations_bp,
    buydowns_bp,
    disclosures_bp,
    forfeitures_bp,
    clock_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    code = exc.code or 500
    if code == 404:
        return error("ERR_RESOURCE_NOT_FOUND", "no such resource path", 404)
    if code == 405:
        return error("ERR_RESOURCE_NOT_FOUND", "method not allowed on this path", 404)
    return error("ERR_INVALID_REQUEST", exc.description or "request rejected", code)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error(exc.error_id, exc.message, exc.http_status)
    if isinstance(exc, HTTPException):
        return handle_http_error(exc)
    return error("ERR_INVALID_REQUEST", "the request could not be processed", 400)


def _exit_on_signal(signum, _frame):
    """Exit promptly on SIGTERM/SIGINT so the port is released for the reboot.

    The harness restarts the server via start.sh before every test; a process
    that keeps the listening socket after being signalled would make the next
    boot fail to bind.
    """
    sys.stderr.flush()
    os._exit(0)


for _sig in (signal.SIGTERM, signal.SIGINT):
    signal.signal(_sig, _exit_on_signal)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )