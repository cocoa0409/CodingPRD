"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask, jsonify

import util
from errors import ApiError


def create_app():
    app = Flask(__name__)

    from routes_clock import bp as clock_bp
    from routes_gpa import bp as gpa_bp
    from routes_clinics import bp as clinics_bp
    from routes_agreements import bp as agreements_bp
    from routes_analyzers import bp as analyzers_bp
    from routes_service_cases import bp as cases_bp
    from routes_reagent import bp as reagent_bp
    from routes_lab import bp as lab_bp
    for bp in (clock_bp, gpa_bp, clinics_bp, agreements_bp, analyzers_bp,
               cases_bp, reagent_bp, lab_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify({
            "meta": util.meta(),
            "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message},
        }), e.http_status

    @app.errorhandler(404)
    def _not_found(_e):
        return jsonify({
            "meta": util.meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": "route not found"},
        }), 404

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return jsonify({
            "meta": util.meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": "method not allowed"},
        }), 405

    @app.errorhandler(Exception)
    def _internal(_e):
        return jsonify({
            "meta": util.meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST",
                     "message": "internal error"},
        }), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
