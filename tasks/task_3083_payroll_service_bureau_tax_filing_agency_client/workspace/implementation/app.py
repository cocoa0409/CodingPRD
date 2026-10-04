"""Flask entry point: app setup, error handlers, route registration."""

import os
from flask import Flask, jsonify

import errors as err
from response import error_response


def create_app():
    app = Flask(__name__)

    @app.errorhandler(err.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, err.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    from routes_clock import bp as clock_bp
    from routes_jurisdictions import bp as jurisdictions_bp
    from routes_clients import bp as clients_bp
    from routes_registrations import bp as registrations_bp
    from routes_payroll import bp as payroll_bp
    from routes_impounds import bp as impounds_bp
    from routes_deposits import bp as deposits_bp
    from routes_returns import bp as returns_bp
    from routes_amendments import bp as amendments_bp
    from routes_notices import bp as notices_bp
    from routes_wage_statements import bp as wage_bp
    from routes_assessments import bp as assessments_bp

    for bp in (clock_bp, jurisdictions_bp, clients_bp, registrations_bp, payroll_bp,
               impounds_bp, deposits_bp, returns_bp, amendments_bp, notices_bp,
               wage_bp, assessments_bp):
        app.register_blueprint(bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
