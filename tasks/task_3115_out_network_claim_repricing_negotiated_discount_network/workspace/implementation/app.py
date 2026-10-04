"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask

import errors
from response import error_response, success_object
import routes_core
import routes_claims
import routes_flows


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.not_found("Resource not found"))

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, errors.ApiError):
            return error_response(e)
        return error_response(errors.ApiError(
            "ERR_INVALID_REQUEST", str(e), 400))

    routes_core.register(app)
    routes_claims.register(app)
    routes_flows.register(app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
