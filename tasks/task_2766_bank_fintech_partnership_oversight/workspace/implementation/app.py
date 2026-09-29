"""Bank-Fintech Partnership Oversight API — entry point.

Storage is in-memory only and starts completely empty on every boot: no entity is
seeded, preloaded or hardcoded here or in any module.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import respond
import routes_agreement
import routes_complaint
import routes_cycle
import routes_diligence
import routes_marketing
import routes_partner
import routes_settlement
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (routes_partner, routes_diligence, routes_agreement, routes_marketing,
               routes_settlement, routes_complaint, routes_cycle):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(respond.error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return jsonify(respond.error_body("ERR_NOT_FOUND", "resource not found")), 404
    if exc.code == 405:
        return jsonify(respond.error_body("ERR_METHOD_NOT_ALLOWED",
                                          "method not allowed")), 405
    if exc.code in (400, 415):
        return jsonify(respond.error_body("ERR_VALIDATION",
                                          exc.description or "invalid request")), 422
    return jsonify(respond.error_body("ERR_INTERNAL", exc.description or "error")), \
        exc.code or 500


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return jsonify(respond.error_body("ERR_INTERNAL", str(exc))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
