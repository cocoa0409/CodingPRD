"""Consulting Bench Management API -- Flask application factory.

All state lives in process memory (store.py) and every collection boots empty:
nothing is seeded, preloaded or hardcoded, so a fresh process is a fresh system.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error
from errors import STATUS, ApiError
from ops import snapshot_groups
from routes_assign import bp as assign_bp
from routes_bench import bp as bench_bp
from routes_demand import bp as demand_bp
from routes_finance import bp as finance_bp
from routes_partner import bp as partner_bp
from routes_people import bp as people_bp
from routes_taxonomy import bp as taxonomy_bp

BLUEPRINTS = (
    taxonomy_bp,
    people_bp,
    demand_bp,
    assign_bp,
    bench_bp,
    partner_bp,
    finance_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _before():
        snapshot_groups()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_INVALID_REQUEST", "No such route.", 404)
        if exc.code == 405:
            return error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)
        return error("ERR_INVALID_REQUEST", exc.description or "Malformed request.", exc.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
