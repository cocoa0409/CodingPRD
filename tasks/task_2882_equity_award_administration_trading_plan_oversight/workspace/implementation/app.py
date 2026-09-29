"""Equity Award Administration & Trading Plan Oversight API."""

import os
import sys
import traceback

from flask import Flask, jsonify

import envelope
from errors import ApiError
from routes_cycles import bp as cycles_bp
from routes_grants import bp as grants_bp
from routes_participants import bp as participants_bp
from routes_plans import bp as plans_bp
from routes_preclearance import bp as preclearance_bp
from routes_trading_plans import bp as trading_plans_bp
from routes_vesting import bp as vesting_bp
from routes_windows import bp as windows_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.register_blueprint(plans_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(grants_bp)
    app.register_blueprint(cycles_bp)
    app.register_blueprint(vesting_bp)
    app.register_blueprint(windows_bp)
    app.register_blueprint(preclearance_bp)
    app.register_blueprint(trading_plans_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        body = envelope.error_body(
            "ERR_INVALID_REQUEST", "No route matches the requested path.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        body = envelope.error_body(
            "ERR_INVALID_REQUEST", "The method is not allowed for this path.")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_bad_request(_err):
        body = envelope.error_body(
            "ERR_INVALID_REQUEST", "The request body could not be parsed.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        traceback.print_exc(file=sys.stderr)
        body = envelope.error_body("ERR_INVALID_REQUEST", "Unexpected server error.")
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
