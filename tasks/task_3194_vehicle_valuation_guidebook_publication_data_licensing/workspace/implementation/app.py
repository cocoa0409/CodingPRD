"""Flask application entry point."""
from __future__ import annotations

import os
import sys

# Make sibling packages importable when invoked as `python3 app.py`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.regions import bp as regions_bp
    from routes.sources import bp as sources_bp
    from routes.configurations import bp as configurations_bp
    from routes.batches import bp as batches_bp
    from routes.series import bp as series_bp
    from routes.editions import bp as editions_bp
    from routes.market_shifts import bp as market_shifts_bp
    from routes.consumer_profiles import bp as consumer_profiles_bp
    from routes.cash_offers import bp as cash_offers_bp
    from routes.license_agreements import bp as license_agreements_bp
    from routes.methodologies import bp as methodologies_bp
    from routes.condition_standards import bp as condition_standards_bp
    from routes.disputes import bp as disputes_bp
    from routes.clock import bp as clock_bp

    app.register_blueprint(regions_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(configurations_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(editions_bp)
    app.register_blueprint(market_shifts_bp)
    app.register_blueprint(consumer_profiles_bp)
    app.register_blueprint(cash_offers_bp)
    app.register_blueprint(license_agreements_bp)
    app.register_blueprint(methodologies_bp)
    app.register_blueprint(condition_standards_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        from errors import not_found
        return error_response(not_found("route not found"))

    @app.errorhandler(405)
    def handle_405(err):
        from errors import invalid_input
        return error_response(invalid_input("method not allowed"))

    @app.errorhandler(Exception)
    def handle_uncaught(err):
        # Surface unexpected errors as a 400 rather than Flask's HTML 500
        from errors import ApiError as _AE
        if isinstance(err, _AE):
            return error_response(err)
        import traceback
        traceback.print_exc()
        e = ApiError("ERR_INTERNAL", 500, f"internal error: {err}")
        return error_response(e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
