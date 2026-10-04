"""Entry point: Flask app, error handlers, route registration."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from errors import ApiError
from response import error_response
from routes import catalog, delivery, devices, financing, orders, post_sale


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(catalog.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(delivery.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(post_sale.bp)
    app.register_blueprint(financing.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_VALIDATION", 400, "route not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_VALIDATION", 400, "method not allowed")

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_VALIDATION", 400, "internal error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
