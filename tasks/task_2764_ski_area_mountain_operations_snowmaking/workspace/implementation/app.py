"""Ski Area Mountain Operations & Snowmaking API."""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

import db
import response
from errors import ApiError
from routes.clock import bp as clock_bp
from routes.seasons import bp as seasons_bp
from routes.lifts import bp as lifts_bp
from routes.terrain import bp as terrain_bp
from routes.pumps import bp as pumps_bp
from routes.sessions import bp as sessions_bp
from routes.grooming import bp as grooming_bp
from routes.patrol import bp as patrol_bp
from routes.dayplans import bp as dayplans_bp

API_PREFIX = "/mountain-ops"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(clock_bp)
    for blueprint in (seasons_bp, lifts_bp, terrain_bp, pumps_bp, sessions_bp,
                      grooming_bp, patrol_bp, dayplans_bp):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.before_request
    def _init_request():
        g.touched = {}

    @app.errorhandler(ApiError)
    def _api_error(exc):
        g.touched = {}
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        g.touched = {}
        if exc.code == 404:
            return response.error_response(
                "ERR_RECORD_NOT_FOUND", "Resource not found", 404)
        if exc.code == 405:
            return response.error_response(
                "ERR_INVALID_REQUEST", "Method not allowed for this resource", 400)
        return response.error_response(
            "ERR_INVALID_REQUEST", exc.description or "Bad request",
            exc.code if exc.code and exc.code < 500 else 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        g.touched = {}
        return response.error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
