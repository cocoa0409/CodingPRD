"""Implementation package for the Student Ride Matching API."""

from decimal import Decimal

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, ApiError
from response import error_response


class DecimalJSONProvider(__import__("flask").json.provider.DefaultJSONProvider):
    """Serialise any residual Decimal as a JSON number, never as a string."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj == obj.to_integral_value():
                return int(obj)
            return float(obj)
        return super().default(obj)


def create_app():
    app = Flask(__name__)
    app.json = DecimalJSONProvider(app)

    # api_prefix "/student-rides" plus the "/_<name>" test-driving endpoints.
    from routes import (
        billing,
        contracts,
        districts,
        drivers,
        geofences,
        incidents,
        monitoring,
        ride_requests,
        riders,
        trips,
    )

    for module in (districts, riders, drivers, contracts, ride_requests,
                   trips, incidents, geofences, billing, monitoring):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body, status = error_response(exc.error_id, exc.message, exc.http_status)
        return jsonify(body), status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        body, status = error_response(
            ERR_NOT_FOUND if exc.code == 404 else ERR_INVALID_REQUEST,
            exc.description or "The request could not be satisfied.",
            exc.code or 400,
        )
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        body, status = error_response(ERR_INVALID_REQUEST, str(exc) or "Unexpected error.", 400)
        return jsonify(body), status

    @app.get("/")
    def health():
        return jsonify({"status": "ok"}), 200

    return app