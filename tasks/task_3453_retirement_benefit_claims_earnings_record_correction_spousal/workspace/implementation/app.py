"""Application bootstrap: Flask app, blueprint registration, and the
envelope-shaped error handlers. The store starts empty on every boot; the
logical clock defaults to 2026-09-01T00:00:00Z (PRD §2.4).
"""

import os

from flask import Flask

from envelope import error_body, ok
from errors import ApiError, ERR_INVALID_REQUEST

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_claim_reads
import routes_claims
import routes_corrections
import routes_overpayments
import routes_payees
import routes_platform
import routes_relationships
import routes_wages
import routes_workers

for module in (
    routes_workers,
    routes_wages,
    routes_corrections,
    routes_relationships,
    routes_claims,
    routes_claim_reads,
    routes_overpayments,
    routes_payees,
    routes_platform,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_body(ApiError(ERR_INVALID_REQUEST, "Unknown path."))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_body(ApiError(ERR_INVALID_REQUEST, "Method not allowed on this path."))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_body(err)
    return error_body(ApiError(ERR_INVALID_REQUEST, f"Unexpected server error: {err}"))


@app.route("/_health", methods=["GET"])
def health():
    return ok({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
