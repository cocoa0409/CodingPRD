"""Entry point: app factory, error handlers, route registration."""
import os
from flask import Flask

from errors import ApiError
from response import error_response

from routes.advisors import bp as advisors_bp
from routes.territories import bp as territories_bp
from routes.branches import bp as branches_bp
from routes.administrators import bp as administrators_bp
from routes.training import bp as training_bp
from routes.production import bp as production_bp
from routes.financials import bp as financials_bp
from routes.goodwill import bp as goodwill_bp
from routes.compliance import bp as compliance_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(advisors_bp)
    app.register_blueprint(territories_bp)
    app.register_blueprint(branches_bp)
    app.register_blueprint(administrators_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(production_bp)
    app.register_blueprint(financials_bp)
    app.register_blueprint(goodwill_bp)
    app.register_blueprint(compliance_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
