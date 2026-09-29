"""Public-land grazing permit administration service.

Flask application factory and process entry point. Storage is entirely in memory
(see store.py); every process start begins with empty collections and a logical
clock parked at the epoch declared in constants.py.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
import routes_aoi
import routes_bills
import routes_decisions
import routes_land
import routes_monitoring
import routes_ops
import routes_permits
import store

MODULES = (
    routes_land,
    routes_permits,
    routes_aoi,
    routes_bills,
    routes_monitoring,
    routes_decisions,
    routes_ops,
)

HTTP_ERROR_IDS = {
    400: "ERR_VALIDATION",
    404: "ERR_NOT_FOUND",
    405: "ERR_METHOD_NOT_ALLOWED",
}


class Serialized(object):
    """Every request runs under the store's lock, so the threaded server never
    interleaves two mutations of the same in-memory record."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with store.LOCK:
            return self.wsgi_app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in MODULES:
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        error_id = HTTP_ERROR_IDS.get(err.code, "ERR_INTERNAL")
        status = err.code if err.code else 500
        return jsonify(envelope.error_body(error_id, err.description)), status

    @app.errorhandler(Exception)
    def _unexpected(err):
        return jsonify(envelope.error_body("ERR_INTERNAL", str(err))), 500

    app.wsgi_app = Serialized(app.wsgi_app)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
