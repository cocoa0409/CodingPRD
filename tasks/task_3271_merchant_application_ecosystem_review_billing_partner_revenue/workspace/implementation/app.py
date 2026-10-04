"""App entry point: Flask app assembly, error handlers."""
import os
from flask import Flask

from errors import ApiError, err_response
import routes_core
import routes_marketplace
import routes_billing


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_marketplace.bp)
    app.register_blueprint(routes_billing.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_response("ERR_INVALID_REQUEST", 400, f"bad request: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
