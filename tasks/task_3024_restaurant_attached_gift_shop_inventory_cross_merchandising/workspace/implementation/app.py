"""Restaurant-Attached Gift Shop API — entry point.

Stateless across boots: every table in db.py starts empty, the logical clock
starts at 2026-09-01T00:00:00Z, and no entity is seeded anywhere.  Tests build
all preconditions through the declared endpoints.
"""

import os
import sys
import traceback

from flask import Flask, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402
from errors import ApiError  # noqa: E402
from response import error as error_body  # noqa: E402
from routes import catalog, clearance, guest_checks, planograms, receipts, staff_shifts, \
    store_days, transfers  # noqa: E402

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------

for module in (catalog, store_days, guest_checks, receipts, clearance,
               staff_shifts, transfers, planograms):
    app.register_blueprint(module.bp)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(exc):
    body, status = error_body(exc.error_id, exc.message, exc.http_status)
    return jsonify(body), status


@app.errorhandler(404)
def handle_not_found(_exc):
    # A request that matches no resource at all and carries no typed path
    # segment reports the generic ERR_NOT_FOUND (PRD 2.7).
    body, status = error_body(
        "ERR_NOT_FOUND",
        "The requested resource does not exist.",
        404)
    return jsonify(body), status


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    body, status = error_body(
        "ERR_INVALID_REQUEST",
        "The HTTP method is not supported for this path.",
        400)
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    traceback.print_exc()
    body, status = error_body(
        "ERR_INVALID_REQUEST",
        "The request could not be processed: %s" % exc,
        400)
    return jsonify(body), status


@app.before_request
def _bootstrap():
    """Keep the store in-memory only; nothing is persisted between boots."""
    return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)