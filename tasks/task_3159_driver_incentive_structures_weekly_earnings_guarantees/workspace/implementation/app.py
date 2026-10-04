"""App entry point: Flask app, error handlers, route registration, clock endpoint."""
import os

from flask import Flask, request

import db
from errors import ApiError, err_invalid_request
from middleware import require_roles
from response import error_response, success_object
from services import iso_now, parse_iso

from routes_markets import bp as markets_bp
from routes_drivers import bp as drivers_bp
from routes_programs import bp as programs_bp
from routes_forecasts import bp as forecasts_bp
from routes_enrollments import bp as enrollments_bp
from routes_rides import bp as rides_bp
from routes_fraud import bp as fraud_bp
from routes_settlements import bp as settlements_bp
from routes_statements import bp as statements_bp
from routes_appeals import bp as appeals_bp
from routes_shortfalls import bp as shortfalls_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(markets_bp)
    app.register_blueprint(drivers_bp)
    app.register_blueprint(programs_bp)
    app.register_blueprint(forecasts_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(rides_bp)
    app.register_blueprint(fraud_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(statements_bp)
    app.register_blueprint(appeals_bp)
    app.register_blueprint(shortfalls_bp)

    @app.post("/_clock/set_current_utc")
    @require_roles("PlatformAdmin")
    def set_clock(_user_id, _role):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise err_invalid_request("JSON body must be an object")
        to_iso8601 = body.get("to_iso8601")
        if not isinstance(to_iso8601, str):
            raise err_invalid_request("to_iso8601 is required")
        dt = parse_iso(to_iso8601, "to_iso8601")
        db.set_clock(dt)
        return success_object({"current_utc": iso_now(dt)})

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
