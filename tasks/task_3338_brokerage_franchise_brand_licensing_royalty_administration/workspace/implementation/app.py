"""Entry point: Flask app assembly, error handlers, foreground server."""
import os

from flask import Flask

import envelope
from errors import ApiError
from routes_agreements import bp as agreements_bp
from routes_billing import bp as billing_bp
from routes_core import bp as core_bp
from routes_funds import bp as funds_bp
from routes_ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except Exception:
        pass

    for bp in (core_bp, agreements_bp, billing_bp, funds_bp, ops_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.api_error(e)

    @app.errorhandler(404)
    def handle_not_found(e):
        return envelope.err('ERR_NOT_FOUND', 404, 'resource not found')

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return envelope.err('ERR_NOT_FOUND', 404, 'resource not found')

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return envelope.err('ERR_INTERNAL', 500, f'internal error: {e}')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')), threaded=True)
