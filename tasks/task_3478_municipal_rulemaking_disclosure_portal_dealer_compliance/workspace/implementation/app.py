"""MSRB API entry point: app creation, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from respond import error as error_response
from routes.clock import bp as clock_bp
from routes.disclosures import bp as disclosures_bp
from routes.enforcement import bp as enforcement_bp
from routes.organizations import bp as organizations_bp
from routes.professionals import bp as professionals_bp
from routes.rulemaking import bp as rulemaking_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.trades import bp as trades_bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(organizations_bp)
    app.register_blueprint(rulemaking_bp)
    app.register_blueprint(disclosures_bp)
    app.register_blueprint(professionals_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(enforcement_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "Route not found.", 404))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", "Internal server error.", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
