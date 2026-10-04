"""Flask entry point: blueprint registration and error handlers."""

import os

from flask import Flask

import routes_centers
import routes_examinees
import routes_irregularities
import routes_registrations
import routes_scores
import routes_sessions
from errors import ApiError
from response import err


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_centers.bp)
    app.register_blueprint(routes_sessions.bp)
    app.register_blueprint(routes_examinees.bp)
    app.register_blueprint(routes_registrations.bp)
    app.register_blueprint(routes_irregularities.bp)
    app.register_blueprint(routes_scores.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return err(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return err('ERR_NOT_FOUND', 404, 'resource not found')

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return err('ERR_NOT_FOUND', 404, 'resource not found')

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return err('ERR_INTERNAL', 500, 'internal error')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
