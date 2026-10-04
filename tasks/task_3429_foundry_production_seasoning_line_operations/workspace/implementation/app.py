"""Flask entry point: blueprint registration and error handlers."""
import os

from flask import Flask

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_allocations import bp as allocations_bp
    from routes_clock import bp as clock_bp
    from routes_defects import bp as defects_bp
    from routes_env import bp as env_bp
    from routes_inventory import bp as inventory_bp
    from routes_melts import bp as melts_bp
    from routes_molds import bp as molds_bp
    from routes_orders import bp as orders_bp
    from routes_outlet import bp as outlet_bp
    from routes_products import bp as products_bp
    from routes_seasoning import bp as seasoning_bp
    from routes_units import bp as units_bp

    for bp in (
        products_bp,
        orders_bp,
        melts_bp,
        molds_bp,
        units_bp,
        defects_bp,
        seasoning_bp,
        env_bp,
        inventory_bp,
        allocations_bp,
        outlet_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.error(e.status, e.error_id, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return envelope.error(404, "ERR_RESOURCE_NOT_FOUND", "resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return envelope.error(404, "ERR_RESOURCE_NOT_FOUND", "resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return envelope.error(500, "ERR_INTERNAL", f"internal error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
