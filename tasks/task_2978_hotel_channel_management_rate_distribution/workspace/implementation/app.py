"""Hotel Channel Distribution API — Flask application entry point.

State lives in plain in-memory dicts (see store.py); every process start is a
completely empty system with the logical clock parked at 2026-08-01T00:00:00Z.
"""

import os

from flask import Flask

import envelope
import store
from errors import ApiError

import routes_analytics
import routes_booking
import routes_channel
import routes_dist
import routes_inventory
import routes_mapping
import routes_promotion
import routes_property
import routes_rate


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    store.reset()

    app.register_blueprint(routes_property.bp)
    app.register_blueprint(routes_channel.bp)
    app.register_blueprint(routes_rate.bp)
    app.register_blueprint(routes_mapping.bp)
    app.register_blueprint(routes_inventory.bp)
    app.register_blueprint(routes_promotion.bp)
    app.register_blueprint(routes_dist.bp)
    app.register_blueprint(routes_booking.bp)
    app.register_blueprint(routes_analytics.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error("ERR_INVALID_REQUEST", "No such resource path.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error("ERR_INVALID_REQUEST",
                              "Method not allowed on this path.", 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return envelope.error("ERR_INVALID_REQUEST", "Malformed request.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
