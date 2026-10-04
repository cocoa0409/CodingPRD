"""Flask application entry point."""

import os

from flask import Flask

from errors import ApiError
from response import err_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_core import bp as core_bp
    from routes_agreements_waves import bp as aw_bp
    from routes_contracts import bp as contracts_bp
    from routes_revenue import bp as revenue_bp
    from routes_incentives import bp as incentives_bp
    from routes_governance import bp as governance_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(aw_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(revenue_bp)
    app.register_blueprint(incentives_bp)
    app.register_blueprint(governance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return err_body("ERR_INVALID_REQUEST", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return err_body("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(400)
    def handle_400(e):
        return err_body("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err_body("ERR_INVALID_REQUEST", str(e), 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
