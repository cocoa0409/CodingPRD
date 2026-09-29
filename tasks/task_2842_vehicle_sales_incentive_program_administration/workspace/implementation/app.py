"""Vehicle Sales Incentive Program Administration service.

A single Flask process holding all state in memory. Nothing is seeded: every
collection starts empty on every boot and tests build all state through the
declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes import batches, claims, clock_endpoint, dealers, deliveries, objectives, programs

API_PREFIX = "/incentives"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs.bp, url_prefix=API_PREFIX)
    app.register_blueprint(objectives.bp, url_prefix=API_PREFIX)
    app.register_blueprint(dealers.bp, url_prefix=API_PREFIX)
    app.register_blueprint(deliveries.bp, url_prefix=API_PREFIX)
    app.register_blueprint(claims.bp, url_prefix=API_PREFIX)
    app.register_blueprint(batches.bp, url_prefix=API_PREFIX)
    app.register_blueprint(clock_endpoint.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_NOT_FOUND"
        elif status == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        else:
            error_id = "ERR_INVALID_REQUEST"
        return response.error_response(error_id, error.description, status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return response.error_response("ERR_INTERNAL", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
