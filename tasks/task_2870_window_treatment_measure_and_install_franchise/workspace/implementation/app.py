"""Window Treatment Measure-and-Install Franchise API.

Flask entry point: blueprint registration and the error envelope handlers.
No entity data is ever seeded -- the in-memory store starts empty on every boot.
"""

import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_admin
import routes_consult
import routes_quote
import routes_order
import routes_install


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(routes_admin.bp)
    app.register_blueprint(routes_consult.bp)
    app.register_blueprint(routes_quote.bp)
    app.register_blueprint(routes_order.bp)
    app.register_blueprint(routes_install.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return respond_error("ERR_INVALID_REQUEST", "unknown resource path", 404)
        if exc.code == 405:
            return respond_error("ERR_INVALID_REQUEST", "method not allowed", 405)
        if exc.code == 400:
            return respond_error("ERR_INVALID_REQUEST", "malformed request", 400)
        return respond_error("ERR_INVALID_REQUEST", exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        traceback.print_exc()
        return respond_error("ERR_INVALID_REQUEST", "unhandled server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
