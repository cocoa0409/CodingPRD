# Analog Direct Supply API — Flask entry point.
import os

from flask import Flask

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)

    from routes_allocation import bp as allocation_bp
    from routes_capacity import bp as capacity_bp
    from routes_clock import bp as clock_bp
    from routes_customers import bp as customers_bp
    from routes_designs import bp as designs_bp
    from routes_eol import bp as eol_bp
    from routes_ltb import bp as ltb_bp
    from routes_orders import bp as orders_bp
    from routes_parts import bp as parts_bp
    from routes_pricing import bp as pricing_bp
    from routes_qual import bp as qual_bp

    app.register_blueprint(parts_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pricing_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(capacity_bp)
    app.register_blueprint(allocation_bp)
    app.register_blueprint(eol_bp)
    app.register_blueprint(ltb_bp)
    app.register_blueprint(qual_bp)
    app.register_blueprint(designs_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error(err)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return envelope.error(ApiError("ERR_NOT_FOUND", 404, "No such route"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return envelope.error(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))

    @app.errorhandler(500)
    def handle_internal(_err):
        return envelope.error(ApiError("ERR_INTERNAL", 500, "Internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
