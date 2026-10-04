"""Entry point: Flask app assembly, error handlers, route registration."""
import os
import traceback

from flask import Flask

from errors import ApiError, api_error
from routes_config import bp as config_bp
from routes_coordination import bp as coordinations_bp
from routes_dissemination import bp as records_bp
from routes_emergency import bp as emergency_bp
from routes_platform import bp as platform_bp
from routes_products import bp as products_bp
from routes_storms import bp as storms_bp
from routes_verification import bp as verification_bp
from util import error_envelope


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        config_bp,
        storms_bp,
        products_bp,
        coordinations_bp,
        records_bp,
        verification_bp,
        emergency_bp,
        platform_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_envelope(err)

    @app.errorhandler(404)
    def _handle_404(_err):
        return error_envelope(
            ApiError("ERR_INVALID_REQUEST", 404, "The requested path does not exist.")
        )

    @app.errorhandler(405)
    def _handle_405(_err):
        return error_envelope(
            ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed for this path.")
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        traceback.print_exc()
        return error_envelope(
            ApiError("ERR_INTERNAL", 500, "Internal server error: %s" % err)
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
