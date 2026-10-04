"""Age-Based Book Mailing API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). In-memory store; every boot starts empty
with the logical clock at exactly 2026-09-01T00:00:00Z.
"""

import os

from flask import Flask

import response
from errors import ApiError
from routes_admin import bp as admin_bp
from routes_agreements import bp as agreements_bp
from routes_children import bp as children_bp
from routes_catalog import bp as catalog_bp
from routes_waves import bp as waves_bp
from routes_invoices import bp as invoices_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(admin_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(children_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(invoices_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.status, err.error_id, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return response.error(404, "ERR_NOT_FOUND", "Route not found")

    @app.errorhandler(405)
    def handle_405(err):
        return response.error(405, "ERR_METHOD_NOT_ALLOWED", "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return response.error(500, "ERR_INTERNAL", "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
