"""App factory, global error handlers, logical clock endpoint, entrypoint."""

import os

from flask import Flask, jsonify

from helpers import (
    ApiError,
    authn,
    body,
    envelope_meta,
    error_body,
    iso_z,
    parse_dt,
    require_role,
    success_object,
    validation,
)
from storage import STORE


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_body(e)

    @app.errorhandler(404)
    def _not_found(e):
        body_out = {
            "meta": envelope_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
        }
        return jsonify(body_out), 404

    @app.errorhandler(405)
    def _method_not_allowed(e):
        body_out = {
            "meta": envelope_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
        }
        return jsonify(body_out), 404

    @app.errorhandler(Exception)
    def _unhandled(e):
        body_out = {
            "meta": envelope_meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
        }
        return jsonify(body_out), 500

    from agreements import bp as agreements_bp
    from bookings import bp as bookings_bp
    from centers import bp as centers_bp
    from events import bp as events_bp
    from funding import bp as funding_bp
    from guests import bp as guests_bp
    from lots import bp as lots_bp
    from shifts import bp as shifts_bp
    from volunteers import bp as volunteers_bp

    app.register_blueprint(centers_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(volunteers_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(lots_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(funding_bp)

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        _, role = authn()
        require_role(role, ("PlatformAdmin",))
        b = body()
        raw = b.get("to_iso8601")
        dt = parse_dt(raw)
        if dt is None:
            validation("to_iso8601 must be a well-formed ISO 8601 timestamp")
        STORE.set_clock(dt)
        return success_object({"current_utc": iso_z(STORE.now())})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
