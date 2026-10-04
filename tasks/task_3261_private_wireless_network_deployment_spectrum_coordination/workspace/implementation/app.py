"""Flask application entry point."""

import os
from flask import Flask

from errors import ApiError, error_response, err
from routes import (alerts, assignments, cells, contracts, coordination,
                    designs, devices, enterprises, leases, misc, remediations,
                    slices, surveys)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    prefix = "/private-wireless"
    for module in (enterprises, surveys, designs, cells, leases, coordination,
                   assignments, devices, slices, contracts, alerts, remediations, misc):
        app.register_blueprint(module.bp, url_prefix=prefix)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err("ERR_NOT_FOUND", "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err("ERR_NOT_FOUND", "Method not allowed on this path"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e)
        return error_response(err("ERR_INVALID_REQUEST", str(e)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
