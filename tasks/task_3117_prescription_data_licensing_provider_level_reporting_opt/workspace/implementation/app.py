"""Entry point: Flask app assembly, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError, err_not_found, err_invalid_request
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.clients import bp as clients_bp
    from routes.suppliers import bp as suppliers_bp
    from routes.agreements import bp as agreements_bp
    from routes.deid_profiles import bp as deid_profiles_bp
    from routes.batches import bp as batches_bp
    from routes.prescribers import bp as prescribers_bp
    from routes.opt_outs import bp as opt_outs_bp
    from routes.jurisdiction_rules import bp as jurisdiction_rules_bp
    from routes.projection import bp as projection_bp
    from routes.products import bp as products_bp
    from routes.periods import bp as periods_bp
    from routes.deliveries import bp as deliveries_bp
    from routes.audit_events import bp as audit_events_bp

    for bp in (
        clock_bp, clients_bp, suppliers_bp, agreements_bp, deid_profiles_bp,
        batches_bp, prescribers_bp, opt_outs_bp, jurisdiction_rules_bp,
        projection_bp, products_bp, periods_bp, deliveries_bp, audit_events_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(err_invalid_request("Request could not be processed"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
