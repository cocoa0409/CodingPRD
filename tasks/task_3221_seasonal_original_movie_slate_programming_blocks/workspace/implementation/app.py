"""Flask app entry point."""
import os

from flask import Flask

from errors import ApiError, err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

import routes_core
import routes_titles
import routes_talent
import routes_production
import routes_programming
import routes_commerce


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_titles.bp)
    app.register_blueprint(routes_talent.bp)
    app.register_blueprint(routes_production.bp)
    app.register_blueprint(routes_programming.bp)
    app.register_blueprint(routes_commerce.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_generic(e):
        # Convert unexpected exceptions into a 400 — keeps the envelope shape
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
