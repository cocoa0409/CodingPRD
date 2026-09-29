"""Multifamily Physical Inspection Readiness API.

A single Flask process holding every row in memory. Nothing is seeded: a fresh
boot starts with twelve empty collections and a logical clock reading exactly
2026-08-01T00:00:00Z.
"""

import os
from decimal import Decimal

from flask import Flask, jsonify
from flask.json.provider import DefaultJSONProvider

import envelope
from errors import ApiError
from routes import (
    appeals,
    capital,
    deficiencies,
    inspections,
    plans,
    portfolio,
    selections,
    standards,
    sweeps,
    testing,
    workorders,
)

BLUEPRINTS = (
    standards.bp,
    portfolio.bp,
    sweeps.bp,
    workorders.bp,
    inspections.bp,
    selections.bp,
    deficiencies.bp,
    appeals.bp,
    plans.bp,
    capital.bp,
    testing.bp,
)


class ApiJSONProvider(DefaultJSONProvider):
    """Decimal is the only arithmetic type in the domain; never float."""

    sort_keys = False

    @staticmethod
    def default(value):
        if isinstance(value, Decimal):
            return float(value)
        return DefaultJSONProvider.default(value)


def create_app():
    app = Flask(__name__)
    app.json = ApiJSONProvider(app)
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(envelope.error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return (
            jsonify(
                envelope.error_body(
                    "ERR_INVALID_REQUEST", "The request could not be understood."
                )
            ),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(exc):
        return (
            jsonify(
                envelope.error_body(
                    "ERR_INVALID_REQUEST", "No route matches this path."
                )
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return (
            jsonify(
                envelope.error_body(
                    "ERR_INVALID_REQUEST", "That method is not allowed on this path."
                )
            ),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        return (
            jsonify(envelope.error_body("ERR_INVALID_REQUEST", str(exc))),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
