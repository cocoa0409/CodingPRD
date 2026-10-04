"""Entry point: Flask app, error handlers, route registration, idempotency replay."""

import json
import os

from flask import Flask, request

from db import db
from errors import ApiError
from response import error_response

import routes_land
import routes_community
import routes_incentives
import routes_sales
import routes_trade
import routes_clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_land.bp)
    app.register_blueprint(routes_community.bp)
    app.register_blueprint(routes_incentives.bp)
    app.register_blueprint(routes_sales.bp)
    app.register_blueprint(routes_trade.bp)
    app.register_blueprint(routes_clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return error_response(e)
        app.logger.exception("Unhandled error")
        return error_response(ApiError("ERR_VALIDATION", 400, str(e)))

    @app.after_request
    def record_idempotency(response):
        """Store the original response for successful POSTs so replayed
        Idempotency-Keys return the identical result without side effects."""
        try:
            if request.method != "POST":
                return response
            key = request.headers.get("Idempotency-Key")
            if key is None or key in db.idempotency:
                return response
            if 200 <= response.status_code < 300:
                db.idempotency[key] = {
                    "fingerprint": (request.get_data(cache=True) or b"").decode("utf-8", "replace"),
                    "status": response.status_code,
                    "body": response.get_data(as_text=True),
                }
        except Exception:
            pass
        return response

    @app.before_request
    def replay_idempotency():
        """If this POST's Idempotency-Key was already seen with the same body,
        short-circuit with the stored response."""
        if request.method != "POST":
            return None
        key = request.headers.get("Idempotency-Key")
        if key is None:
            return None
        stored = db.idempotency.get(key)
        if stored is None:
            return None
        fp = (request.get_data(cache=True) or b"").decode("utf-8", "replace")
        if stored["fingerprint"] != fp:
            return None  # let the route raise ERR_IDEMPOTENCY_REPLAY_MISMATCH
        return app.response_class(
            response=stored["body"],
            status=stored["status"],
            content_type="application/json",
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
