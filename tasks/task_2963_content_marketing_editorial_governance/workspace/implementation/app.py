"""Entry point: Flask app, blueprint registration and error envelopes.

The store is in-memory only and starts completely empty on every boot; nothing
here seeds, preloads or hardcodes a single entity row.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import r_assets
import r_briefs
import r_campaigns
import r_claims
import r_experts
import r_gates
import r_items
import r_ops
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (r_campaigns, r_experts, r_briefs, r_items, r_gates,
               r_claims, r_assets, r_ops):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return envelope.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return envelope.error("ERR_NOT_FOUND", "resource not found", 404)
    if exc.code == 405:
        return envelope.error("ERR_INVALID_REQUEST",
                              "method not allowed for this path", 405)
    if exc.code == 400:
        return envelope.error("ERR_INVALID_REQUEST", "malformed request", 400)
    return envelope.error("ERR_INVALID_REQUEST",
                          exc.description or "request failed",
                          exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return envelope.error("ERR_INTERNAL", "unexpected server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            threaded=True,
            use_reloader=False,
            debug=False)
