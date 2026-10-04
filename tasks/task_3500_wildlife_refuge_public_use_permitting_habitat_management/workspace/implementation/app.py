"""App factory, error handlers, blueprint registration, entry point.
Boots clean from a fresh process on every invocation; the store is module
state and starts empty (per-test-server isolation re-launches start.sh)."""
import os
from flask import Flask
from envelope import ApiError, error_resp

import units
import determinations
import permits
import treatments
import closures
import programs
import grazing
import agreements
import citations
import population
import clockctl


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    for bp in (
        units.bp,
        determinations.bp,
        permits.bp,
        treatments.bp,
        closures.bp,
        programs.bp,
        grazing.bp,
        agreements.bp,
        citations.bp,
        population.bp,
        clockctl.bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_resp(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_resp(ApiError('ERR_NOT_FOUND', 'resource not found'))

    @app.errorhandler(405)
    def handle_405(err):
        return error_resp(ApiError('ERR_NOT_FOUND', 'method not allowed on this path'))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_resp(err)
        return error_resp(ApiError('ERR_INTERNAL', 'internal server error'))

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
