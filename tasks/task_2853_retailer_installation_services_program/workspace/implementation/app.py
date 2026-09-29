"""Retailer Installation Services Program API.

Flask application factory and error plumbing. All state is in-memory (see
store.py): a fresh process starts with every collection empty and no seeded
rows of any kind.
"""
import os

from flask import Flask

import envelope
from errors import ApiError
from routes import (assignments, change_orders, clock, config, customers, deliveries,
                    measurements, network, projects, punch, warranty)

BLUEPRINTS = (
    config.bp,
    network.bp,
    customers.bp,
    projects.bp,
    measurements.bp,
    change_orders.bp,
    deliveries.bp,
    assignments.bp,
    punch.bp,
    warranty.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "No route matches this path.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error(
            "ERR_METHOD_NOT_ALLOWED", "This method is not allowed on this path.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.status)
        return envelope.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
