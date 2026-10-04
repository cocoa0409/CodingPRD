"""STB Rail Rate Complaint Adjudication & Transaction Review API.

Flask entry point: registers the per-domain blueprints, applies the lazy
emergency-service-order expiry sweep before every request (PRD 2.5), and maps
ApiError to the standard error envelope. The in-memory store starts empty on
every boot; nothing is seeded.
"""
import os

from flask import Flask

from derived import sweep_eso_expiry
from envelope import error_resp
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_clock import bp as clock_bp
    from routes_carriers import bp as carriers_bp
    from routes_rates import bp as rates_bp
    from routes_service import bp as service_bp
    from routes_mergers import bp as mergers_bp
    from routes_abandonment import bp as abandonment_bp
    from routes_petitions import bp as petitions_bp

    for blueprint in (
            clock_bp, carriers_bp, rates_bp, service_bp,
            mergers_bp, abandonment_bp, petitions_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def _lazy_eso_expiry():
        # Any request processed at a clock reading at or beyond an active
        # order's expires_at observes and applies the expiry before responding.
        sweep_eso_expiry()

    @app.errorhandler(ApiError)
    def _handle_api_error(err):
        return error_resp(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def _handle_not_found(_err):
        return error_resp('ERR_NOT_FOUND', 404, 'No such route')

    @app.errorhandler(405)
    def _handle_method_not_allowed(_err):
        return error_resp('ERR_METHOD_NOT_ALLOWED', 405, 'Method not allowed')

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        return error_resp('ERR_INTERNAL', 500, 'Internal error: {}'.format(err))

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
