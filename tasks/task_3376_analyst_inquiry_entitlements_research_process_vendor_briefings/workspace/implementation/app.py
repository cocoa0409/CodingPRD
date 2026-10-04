"""Analyst Research Entitlements API — application entry point.

The store is in-memory and starts empty on every boot: nothing is seeded,
preloaded or hardcoded.  The logical clock starts at 2026-09-01T00:00:00Z.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (
    analysts,
    briefings,
    clients,
    clock,
    documents,
    events,
    inclusions,
    inquiries,
    sales,
    seats,
    sponsorships,
    vendors,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (
    clock,
    clients,
    seats,
    analysts,
    inquiries,
    documents,
    vendors,
    inclusions,
    briefings,
    sales,
    events,
    sponsorships,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "No such endpoint.", 404))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INTERNAL", str(err), 500))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
