"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

import errors
import response as resp
from routes import admin, accounts, quotes, referrals, policies, claims, audit


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(admin.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(referrals.bp)
    app.register_blueprint(policies.bp)
    app.register_blueprint(claims.bp)
    app.register_blueprint(audit.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return resp.error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return resp.error(errors.not_found())

    @app.errorhandler(405)
    def handle_405(err):
        return resp.error(errors.ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))

    @app.errorhandler(400)
    def handle_400(err):
        return resp.error(errors.validation())

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return resp.error(err)
        return resp.error(errors.ApiError("ERR_VALIDATION", 400, str(err)))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
