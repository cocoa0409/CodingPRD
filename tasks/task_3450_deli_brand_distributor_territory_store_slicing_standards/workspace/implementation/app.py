"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask

import util
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes_accounts import bp as accounts_bp
    from routes_deliveries import bp as deliveries_bp
    from routes_field import bp as field_bp
    from routes_incidents import bp as incidents_bp
    from routes_logs import bp as logs_bp
    from routes_network import bp as network_bp
    from routes_orders import bp as orders_bp
    from routes_promos import bp as promos_bp
    from routes_supply import bp as supply_bp

    for bp in (network_bp, accounts_bp, supply_bp, orders_bp, deliveries_bp,
               field_bp, logs_bp, promos_bp, incidents_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return util.error_response(exc)

    @app.errorhandler(404)
    def _not_found(_exc):
        return util.error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        return util.error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return util.error_response(ApiError("ERR_INTERNAL", 500, "internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
