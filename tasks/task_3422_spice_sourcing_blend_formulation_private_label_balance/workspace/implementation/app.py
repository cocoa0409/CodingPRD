"""Spice Sourcing, Blend Formulation & Private Label Balance — API server.

Flask entry point: registers error handlers and the per-domain blueprints.
The store (state.DB) starts empty on every boot; the logical clock reads
2026-09-01T00:00:00Z until set via POST /_clock/set_current_utc.
"""
import os

from flask import Flask
from werkzeug.exceptions import MethodNotAllowed, NotFound

from errors import ApiError
from helpers import error_response


def create_app():
    app = Flask(__name__)

    app.register_error_handler(ApiError, error_response)
    app.register_error_handler(
        NotFound, lambda e: error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found")))
    app.register_error_handler(
        MethodNotAllowed,
        lambda e: error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found")))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ApiError("ERR_INTERNAL", 500, "Internal error: %s" % (err,)))

    from routes.clock import bp as clock_bp
    from routes.suppliers import bp as suppliers_bp
    from routes.lots import bp as lots_bp
    from routes.formulas import bp as formulas_bp
    from routes.blend_runs import bp as blend_runs_bp
    from routes.lines import bp as lines_bp
    from routes.production_runs import bp as production_runs_bp
    from routes.batches import bp as batches_bp
    from routes.recalls import bp as recalls_bp
    from routes.agreements import bp as agreements_bp
    from routes.reservations import bp as reservations_bp

    for bp in (clock_bp, suppliers_bp, lots_bp, formulas_bp, blend_runs_bp,
               lines_bp, production_runs_bp, batches_bp, recalls_bp,
               agreements_bp, reservations_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
