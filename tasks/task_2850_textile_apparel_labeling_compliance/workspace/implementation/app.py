"""Textile & Apparel Labeling Compliance API — entry point.

The store is in-memory and starts completely empty on every boot: nothing is
seeded, preloaded or hardcoded.  Every entity is created by callers through the
declared endpoints (PRD 4).
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError
from routes.audits import bp as audits_bp
from routes.brands import bp as brands_bp
from routes.clock import bp as clock_bp
from routes.labels import bp as labels_bp
from routes.labtests import bp as labtests_bp
from routes.markets import bp as markets_bp
from routes.origins import bp as origins_bp
from routes.shipments import bp as shipments_bp
from routes.styles import bp as styles_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (clock_bp, markets_bp, brands_bp, styles_bp, labtests_bp,
                  origins_bp, labels_bp, shipments_bp, audits_bp):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_response(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", "No such route.")), 404
    if exc.code == 405:
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", "Method not allowed on this route.")), 405
    if exc.code and 400 <= exc.code < 500:
        return jsonify(error_response(
            "ERR_INVALID_REQUEST", exc.description or "Malformed request.")), exc.code
    return jsonify(error_response(
        "ERR_INVALID_REQUEST", exc.description or "Request failed.")), exc.code or 500


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, (ApiError, HTTPException)):
        raise exc
    app.logger.exception("unhandled error")
    return jsonify(error_response("ERR_INVALID_REQUEST", str(exc))), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
