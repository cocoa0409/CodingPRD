"""Entry point: Flask app, auth hook, error handlers, route registration.

Boots cleanly from a fresh process on every invocation; all state is
in-memory and starts empty. Binds 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask

import middleware
from errors import ERR_NOT_FOUND, ApiError
from response import error_response
from routes_agreements import bp as agreements_bp
from routes_capstones import bp as capstones_bp
from routes_clock import bp as clock_bp
from routes_deliveries import bp as deliveries_bp
from routes_kits import bp as kits_bp
from routes_partners import bp as partners_bp
from routes_programs import bp as programs_bp
from routes_sessions import bp as sessions_bp
from routes_students import bp as students_bp
from routes_territory import bp as territory_bp

BLUEPRINTS = (
    clock_bp,
    territory_bp,
    partners_bp,
    programs_bp,
    agreements_bp,
    deliveries_bp,
    sessions_bp,
    kits_bp,
    capstones_bp,
    students_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.before_request(middleware.authenticate)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.status)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response(ERR_NOT_FOUND, 'Resource not found', 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response(ERR_NOT_FOUND, 'Method not allowed', 405)

    @app.errorhandler(Exception)
    def handle_unexpected(_err):
        return error_response('ERR_INTERNAL', 'Internal server error', 500)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
