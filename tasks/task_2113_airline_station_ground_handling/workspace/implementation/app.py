"""Airline Station Ground Handling API.

In-memory only.  Every collection starts empty on every boot: this process
seeds, preloads and hardcodes no entity of any kind.  Tests build every
precondition through the declared endpoints.
"""
import os
from decimal import Decimal

from flask import Flask, g, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.exceptions import HTTPException

from auth import authenticate
from envelope import respond_error
from errors import ApiError
from store import db

from routes.stations import bp as stations_bp
from routes.subcontractors import bp as subcontractors_bp
from routes.flight_banks import bp as flight_banks_bp
from routes.turns import bp as turns_bp
from routes.agents import bp as agents_bp
from routes.certifications import bp as certifications_bp
from routes.gse_units import bp as gse_units_bp
from routes.turn_resources import bp as turn_resources_bp
from routes.incidents import bp as incidents_bp
from routes.billing import bp as billing_bp
from routes.clock import bp as clock_bp


class ApiJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return DefaultJSONProvider.default(obj)


def create_app():
    app = Flask(__name__)
    app.json = ApiJSONProvider(app)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    for blueprint in (
        stations_bp, subcontractors_bp, flight_banks_bp, turns_bp, agents_bp,
        certifications_bp, gse_units_bp, turn_resources_bp, incidents_bp,
        billing_bp, clock_bp,
    ):
        app.register_blueprint(blueprint)

    @app.before_request
    def _begin():
        g.bumped = set()
        g.holds_lock = False
        db.lock.acquire()
        g.holds_lock = True
        # Step 1 of the order of evaluation applies to every endpoint.
        authenticate()

    @app.teardown_request
    def _end(exc=None):
        if getattr(g, "holds_lock", False):
            g.holds_lock = False
            try:
                db.lock.release()
            except RuntimeError:
                pass

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST", "Method not allowed.", 405)
        if exc.code and 400 <= exc.code < 500:
            return respond_error("ERR_INVALID_REQUEST", exc.description or "Bad request.", exc.code)
        return respond_error("ERR_INVALID_REQUEST", "Unexpected error.", exc.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        app.logger.exception("unhandled error")
        return respond_error("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
