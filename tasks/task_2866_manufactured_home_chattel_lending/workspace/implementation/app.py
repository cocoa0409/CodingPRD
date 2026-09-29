"""Manufactured Home Chattel Lending API.

Flask application factory and error handling. All state lives in memory and is
empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, jsonify

import envelope
import routes_filings
import routes_insurance
import routes_loans
import routes_recovery
import routes_reference
import routes_servicing
import routes_units
import routes_valuations
from errors import ApiError

API_PREFIX = "/chattel"

BLUEPRINTS = (
    routes_reference.bp,
    routes_units.bp,
    routes_valuations.bp,
    routes_loans.bp,
    routes_filings.bp,
    routes_insurance.bp,
    routes_servicing.bp,
    routes_recovery.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return jsonify(envelope.error_body(
            "ERR_NOT_FOUND", "The requested resource does not exist.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return jsonify(envelope.error_body(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        code = getattr(err, "code", None)
        if isinstance(code, int) and 400 <= code < 600:
            return jsonify(envelope.error_body(
                "ERR_INVALID_REQUEST", str(err))), code
        return jsonify(envelope.error_body(
            "ERR_INTERNAL", "An unexpected error occurred: %s" % err)), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
