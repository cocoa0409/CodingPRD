"""Application factory, error handlers, blueprint registration, and launcher."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes.alumina import bp as alumina_bp
from routes.clock import bp as clock_bp
from routes.contracts import bp as contracts_bp
from routes.decisions import bp as decisions_bp
from routes.hedges import bp as hedges_bp
from routes.labor import bp as labor_bp
from routes.permits import bp as permits_bp
from routes.plans import bp as plans_bp
from routes.potlines import bp as potlines_bp
from routes.prices import bp as prices_bp
from routes.restarts import bp as restarts_bp
from routes.smelters import bp as smelters_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        smelters_bp,
        potlines_bp,
        contracts_bp,
        prices_bp,
        hedges_bp,
        alumina_bp,
        decisions_bp,
        restarts_bp,
        permits_bp,
        labor_bp,
        plans_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
