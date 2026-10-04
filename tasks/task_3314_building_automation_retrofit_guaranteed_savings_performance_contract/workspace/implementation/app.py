"""Flask app entrypoint: blueprint registration and error handling."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify

import errors
import routes_identity
import routes_contracts
import routes_baselines
import routes_bundles
import routes_measures
import routes_facilities
import routes_draws
import routes_phases
import routes_reports
import routes_adjustments
import routes_disputes
import routes_toplevel


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (routes_identity.bp, routes_contracts.bp, routes_baselines.bp,
               routes_bundles.bp, routes_measures.bp, routes_facilities.bp,
               routes_draws.bp, routes_phases.bp, routes_reports.bp,
               routes_adjustments.bp, routes_disputes.bp, routes_toplevel.bp):
        app.register_blueprint(bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return errors.err(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return errors.err("ERR_INVALID_REQUEST", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return errors.err("ERR_INVALID_REQUEST", 405, "method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        traceback.print_exc()
        return errors.err("ERR_INVALID_REQUEST", 500, "internal server error")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
