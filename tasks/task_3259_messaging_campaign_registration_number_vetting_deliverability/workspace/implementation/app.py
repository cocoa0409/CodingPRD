"""Flask application factory and entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response


def create_app():
    app = Flask(__name__)

    from routes import accounts, brands, campaigns, numbers, consent, messages
    from routes import feedback, charges, misc

    app.register_blueprint(accounts.bp)
    app.register_blueprint(brands.bp)
    app.register_blueprint(campaigns.bp)
    app.register_blueprint(numbers.bp)
    app.register_blueprint(consent.bp)
    app.register_blueprint(messages.bp)
    app.register_blueprint(feedback.bp)
    app.register_blueprint(charges.bp)
    app.register_blueprint(misc.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_VALIDATION, "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
