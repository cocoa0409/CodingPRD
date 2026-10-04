"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError, err, ERR_INVALID_REQUEST
from response import error_resp, success
import routes_core
import routes_money
import routes_safety


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_money.bp)
    app.register_blueprint(routes_safety.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_resp(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_resp(err(ERR_INVALID_REQUEST, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_resp(err(ERR_INVALID_REQUEST, "Method not allowed"))

    @app.errorhandler(500)
    def handle_500(e):
        return error_resp(err(ERR_INVALID_REQUEST, "Internal server error"))

    @app.get("/")
    def root():
        return success({}, 200)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
