"""Subscription Catalog Licensing API — Flask entry point.

Storage is in-memory only and starts empty on every boot; the logical clock
starts at 2026-09-01T00:00:00Z (PRD sections 2.5 and 2.12).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes.access import bp as access_bp
from routes.analytics import bp as analytics_bp
from routes.base import bp as base_bp
from routes.clock import bp as clock_bp
from routes.licensing import bp as licensing_bp
from routes.membership import bp as membership_bp
from routes.rotation import bp as rotation_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (base_bp, licensing_bp, rotation_bp, membership_bp, access_bp,
                  analytics_bp, clock_bp):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code == 404:
        return error_body("ERR_ENTRY_NOT_FOUND",
                          "No route matches the requested path.", 404)
    if exc.code == 405:
        return error_body("ERR_INVALID_REQUEST",
                          "The method is not allowed on this path.", 405)
    return error_body("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                      exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    import traceback
    traceback.print_exc()
    return error_body("ERR_INVALID_REQUEST",
                      "The request could not be processed.", 400)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
