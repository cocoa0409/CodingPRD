"""ISO residual accounting API -- entry point, error handling, blueprint wiring.

The in-memory store is created empty on import (see store.py) and no entity is
ever seeded, preloaded or hardcoded: every row is built by a client through the
declared API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from apierrors import ApiError
from auth import authenticate
from envelope import error_response
import routes_adjustments
import routes_advances
import routes_agents
import routes_batches
import routes_clock
import routes_ledger
import routes_merchants
import routes_programs
import routes_statements

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(routes_clock.bp)
app.register_blueprint(routes_programs.bp)
app.register_blueprint(routes_agents.bp)
app.register_blueprint(routes_advances.bp)
app.register_blueprint(routes_merchants.bp)
app.register_blueprint(routes_batches.bp)
app.register_blueprint(routes_ledger.bp)
app.register_blueprint(routes_statements.bp)
app.register_blueprint(routes_adjustments.bp)


@app.before_request
def _authenticate():
    """PRD 2.1: the auth check runs ahead of routing concerns."""
    authenticate()


@app.errorhandler(ApiError)
def _handle_api_error(error):
    return error_response(error.error_id, error.message), error.http_status


@app.errorhandler(HTTPException)
def _handle_http_exception(error):
    return error_response("ERR_INVALID_REQUEST", error.description), error.code


@app.errorhandler(Exception)
def _handle_unexpected(error):
    return error_response("ERR_INVALID_REQUEST", str(error)), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
