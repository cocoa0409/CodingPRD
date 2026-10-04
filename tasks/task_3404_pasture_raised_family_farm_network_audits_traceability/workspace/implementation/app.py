"""Pasture-Raised Farm Network API — application entry point.

Flask app wiring: logical clock boot, per-domain blueprint registration, and
envelope-shaped error handlers (PRD 2.2). The store starts empty; entities
are created only through the declared API surface.
"""
import os

from flask import Flask

import clock
from errors import ApiError
from responses import error_response


def create_app():
    app = Flask(__name__)
    clock.boot()

    from routes_farms import bp as farms_bp
    from routes_contracts import bp as contracts_bp
    from routes_audits import bp as audits_bp
    from routes_cas import bp as cas_bp
    from routes_incidents import bp as incidents_bp
    from routes_routes import bp as routes_bp
    from routes_lots import bp as lots_bp
    from routes_retailers import bp as retailers_bp
    from routes_commitments import bp as commitments_bp
    from routes_forecasts import bp as forecasts_bp
    from routes_settlements import bp as settlements_bp
    from routes_clock import bp as clock_bp

    for blueprint in (farms_bp, contracts_bp, audits_bp, cas_bp, incidents_bp,
                      routes_bp, lots_bp, retailers_bp, commitments_bp,
                      forecasts_bp, settlements_bp, clock_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")

    @app.errorhandler(Exception)
    def _unhandled(e):
        return error_response("ERR_INTERNAL", 500, "internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
