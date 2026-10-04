"""Flask app entry point."""
import os

from flask import Flask

import errors
import response
from routes import builders, capacity, catalog, deliveries, liens, orders, takeoffs


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(capacity.bp)
    app.register_blueprint(catalog.bp)
    app.register_blueprint(builders.bp)
    app.register_blueprint(takeoffs.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(deliveries.bp)
    app.register_blueprint(liens.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return response.fail(e)

    @app.errorhandler(404)
    def handle_404(e):
        return response.fail(errors.err_not_found("Route not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return response.fail(errors.err_not_found("Method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return response.fail(errors.ApiError(
            "ERR_INVALID_REQUEST", f"Unexpected: {e}", 400))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
