# Entry point: Flask app, error handlers, blueprint registration.
import os

from flask import Flask, jsonify

import agreements
import claims
import clockroute
import configurations
import dealers
import errors
import families
import orders
import phases
import punches
import windows

app = Flask(__name__)

for module in (dealers, agreements, families, configurations, orders, phases,
               windows, punches, claims, clockroute):
    app.register_blueprint(module.bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return errors.api_error_response(exc)


@app.errorhandler(404)
def handle_not_found(_exc):
    return jsonify(errors.error_response_body(
        "ERR_NOT_FOUND", "No such route")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    return jsonify(errors.error_response_body(
        "ERR_METHOD_NOT_ALLOWED", "Method not allowed on this route")), 405


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unexpected error: %s", exc)
    return jsonify(errors.error_response_body(
        "ERR_INTERNAL", "Internal server error")), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
